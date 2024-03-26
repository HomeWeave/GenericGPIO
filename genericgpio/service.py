import json
import os
import socket
from uuid import getnode, uuid4
from threading import Thread, Event
from enum import Enum
from pathlib import Path

from pyantonlib.plugin import AntonPlugin
from pyantonlib.channel import GenericInstructionController
from pyantonlib.channel import GenericEventController
from pyantonlib.channel import PlatformRequestController
from pyantonlib.channel import SettingsController as SC
from pyantonlib.channel import PlatformResponseController
from pyantonlib.dynamic_app import load_dynamic_app
from pyantonlib.utils import log_info, log_warn
from anton.plugin_pb2 import PipeType
from anton.events_pb2 import GenericEvent
from anton.device_pb2 import DeviceKind
from anton.device_pb2 import DEVICE_STATUS_ONLINE, DEVICE_STATUS_OFFLINE
from anton.device_pb2 import DEVICE_KIND_MOTION_SENSOR
from anton.platform_pb2 import PlatformRequest
from anton.sensor_pb2 import MOTION_DETECTED, NO_MOTION
from anton.gpio_pb2 import EDGE_TYPE_BOTH, PIN_VALUE_HIGH
from anton.ui_pb2 import Page, CustomMessage
from anton.settings_pb2 import SettingsResponse

from genericgpio.settings import Settings


class SettingsController(SC):

    def __init__(self, settings, devices_manager, data_dir):
        self.settings = settings
        self.devices_manager = devices_manager
        self.settings_page = load_dynamic_app(data_dir, 'ui/settings_ui.pb')

        super().__init__({
            "get_settings_ui": self.get_settings_ui,
            "custom_request": self.handle_custom_request
        })

    def get_settings_ui(self, settings_request):
        resp = SettingsResponse(request_id=settings_request.request_id,
                                settings_ui_response=self.settings_page)
        return resp

    def handle_custom_request(self, settings_request):
        payload = settings_request.custom_request.payload
        if payload is None:
            return SettingsResponse(request_id=settings_request.request_id,
                                    custom_response=CustomMessage())

        request = json.loads(payload)

        action = request.get('action')
        handler = getattr(self, 'handle_' + (action or 'default'),
                          self.handle_default)
        payload = handler(request)
        response = CustomMessage(index=settings_request.custom_request.index,
                                 payload=payload)
        return SettingsResponse(request_id=settings_request.request_id,
                                custom_response=response)

    def handle_default(self, request):
        return None

    def handle_get_all_settings(self, request):
        return json.dumps({"type": "settings", "payload": self.settings.props})

    def handle_add_device(self, request):
        self.devices_manager.add_device(request["type"])
        return self.handle_get_all_settings(request)

    def handle_update_name(self, request):
        self.devices_manager.update_name(request["id"], request["value"])
        return self.handle_get_all_settings(request)

    def handle_change_pin(self, request):
        self.devices_manager.change_pin(request["id"], request["value"])
        return self.handle_get_all_settings(request)


class GenericDevice:

    def __init__(self, config, devices_manager, send_event):
        self.devices_manager = devices_manager
        self.send_event = send_event

        self.config = config
        self.device_id = None
        self.device_name = None

        self.reload_config()

    def reload_config(self):
        self.device_id = self.config["id"]
        self.device_name = self.config["name"]

    def start(self):
        event = GenericEvent(device_id=self.device_id)
        event.device.friendly_name = self.device_name
        event.device.device_status = DEVICE_STATUS_ONLINE

        self.fill_device_meta(event)

        self.send_event(event)

    def stop(self):
        event = GenericEvent(device_id=self.device_id)
        event.device.device_status = DEVICE_STATUS_OFFLINE
        self.send_event(event)

    def update_name(self, new_name):
        self.config["name"] = new_name

    def on_change(self, pin, value):
        raise NotImplementedError

    def on_instruction(self, instruction):
        raise NotImplementedError

    def fill_device_meta(self, event):
        raise NotImplementedError

    @staticmethod
    def new_config():
        return {"id": str(uuid4()), "name": "New Device " + str(uuid4())}


class SimpleSensorDevice(GenericDevice):

    def reload_config(self):
        super().reload_config()
        self.pin = int(self.config["pin"])

    def start(self):
        super().start()
        self.devices_manager.subscribe_pin(self, self.pin)

    def stop(self):
        self.devices_manager.unsubscribe_pin(self, self.pin)
        super().stop()

    def change_pin(self, new_pin):
        self.config["pin"] = str(new_pin)

    def fill_device_meta(self, event):
        pass

    def on_change(self, pin, value):
        pass

    @staticmethod
    def new_config():
        config = super(SimpleSensorDevice, SimpleSensorDevice).new_config()
        config["pin"] = 0
        config["type"] = SimpleSensorDevice.__name__
        return config


class MotionSensorDevice(SimpleSensorDevice):

    def fill_device_meta(self, event):
        event.device.device_kind = DEVICE_KIND_MOTION_SENSOR

    def on_change(self, pin, value):
        event = GenericEvent(device_id=self.device_id)
        event.sensor.motion_sensor = MOTION_DETECTED if value else NO_MOTION
        self.send_event(event)

    @staticmethod
    def new_config():
        config = super(MotionSensorDevice, MotionSensorDevice).new_config()
        config["type"] = MotionSensorDevice.__name__
        return config


class SimpleActuatorDevice(GenericDevice):

    def reload_config(self):
        super().reload_config()
        self.pin = int(self.config["pin"])

    def start(self):
        super().start()
        self.devices_manager.subscribe_instruction(self, self.pin)

    def stop(self):
        self.devices_manager.unsubscribe_instruction(self, self.pin)
        super().stop()

    def fill_device_meta(self, event):
        pass

    def on_instruction(self, context, instruction):
        pass

    @staticmethod
    def new_config():
        config = super(SimpleActuatorDevice, SimpleActuatorDevice).new_config()
        config["type"] = SimpleActuatorDevice.__name__
        config["pin"] = 0
        return config


def get_device_class(type_str):
    known_types = [
        SimpleActuatorDevice, SimpleSensorDevice, MotionSensorDevice
    ]
    return {x.__name__: x for x in known_types}.get(type_str, None)


class DevicesManager:

    def __init__(self, config, send_platform_request, send_event):
        self.config = config
        self.send_platform_request = send_platform_request
        self.send_event = send_event
        self.pin_to_devices = {}
        self.id_to_devices = {}

    def start(self):
        self.pin_to_devices = {}
        self.id_to_devices = {}
        for device_config in self.config.get_prop("devices", []):
            device_class = get_device_class(device_config["type"])
            if device_class:
                device = device_class(device_config, self, self.send_event)
                self.id_to_devices[device.device_id] = device
                device.start()

    def stop(self):
        pass

    def on_pin_value_changed(self, pin, value):
        device = self.pin_to_devices.get(pin)
        if not device:
            device.on_change(pin, value)

    def on_instruction(self, context, instruction):
        device = self.pin_to_devices.get(pin)
        if not device:
            device.on_instruction(context, instruction)

    def subscribe_pin(self, device, pin_number):
        req = PlatformRequest()
        req.gpio_request.device_id = device.device_id
        req.gpio_request.gpio_input.pin_number = pin_number
        req.gpio_request.gpio_input.edge_type = EDGE_TYPE_BOTH
        self.send_platform_request(req)

        self.pin_to_devices[pin_number] = device

    def unsubscribe_pin(self, device, pin_number):
        req = PlatformRequest()
        req.gpio_request.device_id = device.device_id
        req.gpio_request.gpio_input.pin_number = pin_number
        req.gpio_request.gpio_input.edge_type = EDGE_TYPE_BOTH
        self.send_platform_request(req)

        self.pin_to_devices.pop(pin_number, None)

    def subscribe_instruction(self, device, pin_number):
        self.pin_to_devices[pin_number] = device

    def unsubscribe_instruction(self, device, pin_number):
        self.pin_to_devices.pop(pin_number, None)

    def add_device(self, device_type):
        cls = get_device_class(device_type)
        if not cls:
            print("Unknown device type:", cls)
            return
        config = cls.new_config()
        cur_devices = self.config.get_prop("devices")
        cur_devices.append(config)
        self.config.set_prop("devices", cur_devices)
        self.stop()
        self.start()

    def update_name(self, device_id, new_name):
        device = self.id_to_devices.get(device_id, None)
        if not device:
            return

        device.stop()
        device.update_name(new_name)
        self.config.flush()
        device.reload_config()
        device.start()

    def change_pin(self, device_id, new_pin):
        device = self.id_to_devices.get(device_id, None)
        if not device:
            return

        device.stop()
        device.change_pin(new_pin)
        self.config.flush()
        device.reload_config()
        device.start()


class GPIOPlugin(AntonPlugin):

    def setup(self, plugin_startup_info):
        self.settings = Settings(plugin_startup_info.data_dir)

        platform_request_controller = PlatformRequestController(lambda obj: 0)
        self.send_platform_request = (
            platform_request_controller.create_client(0, self.on_response))

        event_controller = GenericEventController(lambda call_status: 0)
        self.send_event = event_controller.create_client(0, self.on_response)

        self.devices_manager = DevicesManager(self.settings,
                                              self.send_platform_request,
                                              self.send_event)

        platform_response_controller = PlatformResponseController(
            {"gpio_event": self.devices_manager.on_pin_value_changed})

        instruction_controller = GenericInstructionController(
            {"power_state": self.devices_manager.on_instruction})

        settings_controller = SettingsController(self.settings,
                                                 self.devices_manager,
                                                 plugin_startup_info.data_dir)

        registry = self.channel_registrar()
        registry.register_controller(PipeType.IOT_INSTRUCTION,
                                     instruction_controller)
        registry.register_controller(PipeType.IOT_EVENTS, event_controller)
        registry.register_controller(PipeType.PLATFORM_REQUEST,
                                     platform_request_controller)
        registry.register_controller(PipeType.PLATFORM_RESPONSE,
                                     platform_response_controller)
        registry.register_controller(PipeType.SETTINGS, settings_controller)

    def on_start(self):
        self.devices_manager.start()

    def on_stop(self):
        self.devices_manager.stop()

    def on_response(self, call_status):
        print("Received response:", call_status)
