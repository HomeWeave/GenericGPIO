import json
import os
import socket
from uuid import getnode, uuid4
from threading import Thread, Event
from enum import Enum
from pathlib import Path

from pyantonlib.plugin import AntonPlugin
from pyantonlib.channel import AppHandlerBase, DeviceHandlerBase
from pyantonlib.channel import DefaultProtoChannel
from pyantonlib.dynamic_app import load_dynamic_app
from pyantonlib.utils import log_info, log_warn
from anton.plugin_pb2 import PipeType
from anton.device_pb2 import DeviceKind
from anton.device_pb2 import DEVICE_STATUS_ONLINE, DEVICE_STATUS_OFFLINE
from anton.device_pb2 import DEVICE_KIND_MOTION_SENSOR
from anton.platform_pb2 import PlatformRequest
from anton.sensor_pb2 import MOTION_DETECTED, NO_MOTION
from anton.gpio_pb2 import EDGE_TYPE_BOTH, PIN_VALUE_HIGH
from anton.ui_pb2 import Page, CustomMessage, DynamicAppRequestType

from genericgpio.settings import Settings
from genericgpio.devices import get_device_class


class Channel(DefaultProtoChannel):
    pass


class AppHandler(AppHandlerBase):

    def __init__(self, plugin_startup_info, devices_manager):
        super().__init__(plugin_startup_info, incoming_message_key='action')
        self.devices_manager = devices_manager
        self.register_action('get_all_devices', self.handle_get_all_devices)
        self.register_action('get_available_pins',
                             self.handle_get_available_pins)
        self.register_action('get_supported_device_types',
                             self.handle_get_supported_device_types)
        self.register_action('add_device', self.handle_add_device)

    def get_ui_path(self, app_type):
        if app_type == DynamicAppRequestType.SETTINGS:
            return "ui/settings_ui.pbtxt"

    def handle_get_all_devices(self, requester_id, msg):
        self.send_message(
            {
                "type": "devices",
                "value": {
                    "devices": self.devices_manager.get_devices()
                }
            },
            requester_id=requester_id)

    def handle_get_supported_device_types(self, requester_id, msg):
        self.send_message(
            {
                "type": "supported_devices",
                "value": {
                    "supported_devices": [
                        {
                            "id": "SimpleSensorDevice",
                            "name": "Simple Sensor Device"
                        },
                        {
                            "id": "SimpleActuatorDevice",
                            "name": "Simple Actuator Device"
                        },
                    ]
                }
            },
            requester_id=requester_id)

    def handle_get_available_pins(self, requester_id, msg):
        self.send_message(
            {
                "type": "available_pins",
                "value": {
                    "available_pins": [0, 1, 2, 3]
                }
            },
            requester_id=requester_id)

    def handle_add_device(self, requester_id, msg):
        msg.pop('action', None)
        self.devices_manager.add_device(msg)


class DevicesManager(DeviceHandlerBase):

    def __init__(self, config):
        self.config = config
        self.pin_to_devices = {}
        self.id_to_devices = {}

    def start(self):
        self.pin_to_devices = {}
        self.id_to_devices = {}
        for device_config in self.config.get_prop("devices", []):
            device_class = get_device_class(device_config["type"])
            if device_class:
                device = device_class(device_config, self)
                self.id_to_devices[device.device_id()] = device
                device.start()

    def stop(self):
        for device in self.id_to_devices.values():
            device.stop()

    def handle_platform_response(self, msg, callback):
        platform_response = msg.platform_response
        if platform_response.WhichOneof('response_type') != 'gpio_event':
            return

        gpio_event = platform_response.gpio_event

        if gpio_event.WhichOneof('response_type') != 'pin_state':
            return

        device = self.pin_to_devices.get(gpio_event.pin_state.pin_number)
        if not device:
            device.on_change(gpio_event.pin_state.pin_number,
                             gpio_event.pin_state.pin_value)

    def handle_instruction(self, msg, callback):
        instruction = msg.instruction
        device = self.id_to_devices.get(instruction.device_id, None)
        if device:
            device.on_instruction(context, instruction)
        else:
            log_warn("No device found: " + instruction.device_id)

    def subscribe_pin(self, device, pin_number):
        req = PlatformRequest()
        req.gpio_request.device_id = device.device_id()
        req.gpio_request.gpio_input.pin_number = pin_number
        req.gpio_request.gpio_input.edge_type = EDGE_TYPE_BOTH
        self.send_platform_request(req)

        self.pin_to_devices[pin_number] = device

    def unsubscribe_pin(self, device, pin_number):
        req = PlatformRequest()
        req.gpio_request.device_id = device.device_id()
        req.gpio_request.gpio_input.pin_number = pin_number
        req.gpio_request.gpio_input.edge_type = EDGE_TYPE_BOTH
        self.send_platform_request(req)

        self.pin_to_devices.pop(pin_number, None)

    def get_devices(self):
        return [device.get_config() for device in self.id_to_devices.values()]

    def add_device(self, config):
        cls = get_device_class(config["type"])
        if not cls:
            log_warn("Unknown device type:", cls)
            return

        config = {**cls.new_config(), **config}
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


class GPIOPlugin(AntonPlugin):

    def setup(self, plugin_startup_info):
        self.settings = Settings(plugin_startup_info.data_dir)
        self.devices_manager = DevicesManager(self.settings)
        self.app_handler = AppHandler(plugin_startup_info,
                                      self.devices_manager)

        self.channel = Channel(self.devices_manager, self.app_handler)
        registry = self.channel_registrar()
        registry.register_controller(PipeType.DEFAULT, self.channel)

    def on_start(self):
        self.devices_manager.start()

    def on_stop(self):
        self.devices_manager.stop()
