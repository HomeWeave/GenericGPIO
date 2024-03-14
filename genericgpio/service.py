import json
import os
import socket
from uuid import getnode
from threading import Thread, Event
from enum import Enum
from pathlib import Path

from google.protobuf import json_format

from pyantonlib.plugin import AntonPlugin
from pyantonlib.channel import GenericInstructionController
from pyantonlib.channel import GenericEventController
from pyantonlib.channel import PlatformRequestController
from pyantonlib.channel import SettingsController as SC
from pyantonlib.channel import PlatformResponseController
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
    def __init__(self, settings, data_dir):
        self.settings = settings
        self.settings_ui_path = Path(data_dir) / 'settings_ui.json'

        super().__init__({
            "get_settings_ui": self.get_settings_ui,
            "custom_request": self.handle_custom_request
        })

    def get_settings_ui(self, settings_request):
        with self.settings_ui_path.open() as f:
            page = json_format.Parse(f.read(), Page())

        resp = SettingsResponse(request_id=settings_request.request_id,
                                settings_ui_response=page)
        return resp

    def handle_custom_request(self, settings_request):
        payload = settings_request.custom_request.payload
        if payload is None:
            return SettingsResponse(request_id=settings_request.request_id,
                                    custom_response=CustomMessage())

        request = json.loads(payload)

        payload = None
        if request.get('action') == 'get_all_settings':
            payload = json.dumps({
                "type": "settings",
                "payload": self.settings.props})
        else:
            payload = None

        response = CustomMessage(index=settings_request.custom_request.index,
                                 payload=payload);
        return SettingsResponse(request_id=settings_request.request_id,
                                custom_response=response)


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

    def on_change(self, pin, value):
        raise NotImplementedError

    def on_instruction(self, instruction):
        raise NotImplementedError

    def fill_device_meta(self, event):
        raise NotImplementedError


class SimpleSensorDevice(GenericDevice):
    def reload_config(self):
        super().reload_config()
        self.pin = int(pin_config["pin"])

    def start(self):
        super().start()
        self.devices_manager.subscribe_pin(self, self.pin)

    def stop(self):
        self.devices_manager.unsubscribe_pin(self, self.pin)
        super().stop()

    def fill_device_meta(self, event):
        pass

    def on_change(self, pin, value):
        pass

class MotionSensorDevice(SimpleSensorDevice):
    def fill_device_meta(self, event):
        event.device.device_kind = DEVICE_KIND_MOTION_SENSOR

    def on_change(self, pin, value):
        event = GenericEvent(device_id=self.device_id)
        event.sensor.motion_sensor = MOTION_DETECTED if value else NO_MOTION
        self.send_event(event)


class SimpleActuatorDevice(GenericDevice):
    def reload_config(self):
        super().reload_config()
        self.pin = int(pin_config["pin"])

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


def get_device_class(type_str):
    known_types = [SimpleActuatorDevice, SimpleSensorDevice, MotionSensorDevice]
    return {x.__name__: x for x in known_types}.get(type_str, None)

class DevicesManager:
    def __init__(self, config, send_platform_request, send_event):
        self.config = config
        self.send_platform_request = send_platform_request
        self.send_event = send_event
        self.pin_to_devices = {}

    def start(self):
        self.pin_to_devices = {}
        self.devices = {}
        for device_config in self.config.get_prop("devices", []):
            device_class = get_device_class(device_config["type"])
            if device_class:
                device = device_class(device_config, self, self.send_event)
                device.start()

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


class GPIOPlugin(AntonPlugin):
    def setup(self, plugin_startup_info):
        self.settings = Settings(plugin_startup_info.data_dir)
        settings_controller = SettingsController(self.settings,
                                                 plugin_startup_info.data_dir)

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

        instruction_controller = GenericInstructionController({
            "power_state": self.devices_manager.on_instruction
        })

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

    def on_gpio_instruction(self, value):
        if value.pin_state.pin_value == PIN_VALUE_HIGH:
            self.send_event(self.event_wrapper.motion_detected())
        else:
            self.send_event(self.event_wrapper.no_motion_detected())

