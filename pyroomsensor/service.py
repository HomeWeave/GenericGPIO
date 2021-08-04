import asyncio
import os
import socket
from uuid import getnode
from threading import Thread, Event

from pyantonlib.plugin import AntonPlugin
from pyantonlib.channel import GenericInstructionController
from pyantonlib.channel import GenericEventController
from pyantonlib.channel import PlatformRequestController
from pyantonlib.channel import PlatformResponseController
from pyantonlib.utils import log_info, log_warn
from anton.plugin_pb2 import PipeType
from anton.events_pb2 import GenericEvent
from anton.device_pb2 import DeviceKind
from anton.device_pb2 import DEVICE_STATUS_ONLINE, DEVICE_KIND_MOTION_SENSOR
from anton.platform_pb2 import PlatformRequest
from anton.sensor_pb2 import MOTION_DETECTED, NO_MOTION
from anton.gpio_pb2 import EDGE_TYPE_BOTH, PIN_VALUE_HIGH


class EventWrapper:
    def __init__(self, device_id):
        self.device_id = device_id

    def online_event(self):
        event = GenericEvent(device_id=self.device_id)
        event.device.friendly_name = "Room Sensor"
        event.device.device_kind = DEVICE_KIND_MOTION_SENSOR
        event.device.device_status = DEVICE_STATUS_ONLINE

        capabilities = event.device.capabilities

        return event

    def motion_detected(self):
        event = GenericEvent(device_id=self.device_id)
        event.sensor.motion_sensor = MOTION_DETECTED
        return event

    def no_motion_detected(self):
        event = GenericEvent(device_id=self.device_id)
        event.sensor.motion_sensor = NO_MOTION
        return event


class PlatformRequestWrapper:
    def __init__(self, device_id):
        self.device_id = device_id

    def subscribe_pin(self, pin_number):
        req = PlatformRequest(device_id=self.device_id)
        req.gpio_request.gpio_input.pin_number = pin_number
        req.gpio_request.gpio_input.edge_type = EDGE_TYPE_BOTH
        return req


class RoomSensorPlugin(AntonPlugin):
    def setup(self, plugin_startup_info):
        instruction_controller = GenericInstructionController({})
        event_controller = GenericEventController(lambda call_status: 0)
        self.send_event = event_controller.create_client(0, self.on_response)

        platform_response_controller = PlatformResponseController(
                {"pin_state": self.on_gpio_instruction})
        platform_request_controller = PlatformRequestController(lambda obj: 0)
        self.send_platform_request = (
            platform_request_controller.create_client(0, self.on_response))

        device_id = "room-sensor-" + hex(getnode())
        self.event_wrapper = EventWrapper(device_id)
        self.platform_request_wrapper = PlatformRequestWrapper(device_id)

        registry = self.channel_registrar()
        registry.register_controller(PipeType.IOT_INSTRUCTION,
                                     instruction_controller)
        registry.register_controller(PipeType.IOT_EVENTS, event_controller)
        registry.register_controller(PipeType.PLATFORM_REQUEST,
                                     platform_request_controller)
        registry.register_controller(PipeType.PLATFORM_RESPONSE,
                                     platform_response_controller)

    def on_start(self):
        self.send_event(self.event_wrapper.online_event())
        self.send_platform_request(
                self.platform_request_wrapper.subscribe_pin(4))

    def on_stop(self):
        pass

    def on_response(self, call_status):
        print("Received response:", call_status)

    def on_gpio_instruction(self, value):
        if value.pin_state.pin_value == PIN_VALUE_HIGH:
            self.send_event(self.event_wrapper.motion_detected())
        else:
            self.send_event(self.event_wrapper.no_motion_detected())

