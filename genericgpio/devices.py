from uuid import getnode
from anton.device_pb2 import DeviceKind, DeviceStatus
from anton.state_pb2 import DeviceState
from anton.sensor_pb2 import MotionSensorState
from anton.gpio_pb2 import PinValue
from anton.power_pb2 import PowerState

from pyantonlib.exceptions import BadArguments


class GenericDevice:

    def __init__(self, config, devices_manager):
        self.devices_manager = devices_manager

        self.config = config
        self.device_name = self.config["name"]
        self.device_kind = str_to_device_kind(self.config["kind"])

    def device_id(self):
        raise NotImplementedError

    def get_config(self):
        return {
            "id": self.device_id(),
            "name": self.device_name,
            "kind": device_kind_to_str(self.device_kind)
        }

    def start(self):
        msg = DeviceState(device_id=self.device_id(),
                          friendly_name=self.device_name,
                          device_status=DeviceStatus.DEVICE_STATUS_ONLINE,
                          kind=self.device_kind)
        self.fill_device_meta(msg)
        self.fill_device_state(msg)
        self.devices_manager.send_device_state_updated(msg)

    def stop(self):
        msg = DeviceState(device_id=self.device_id(),
                          device_status=DeviceStatus.DEVICE_STATUS_OFFLINE)
        self.devices_manager.send_device_state_updated(msg)

    def on_change(self, pin, value):
        raise NotImplementedError

    def on_instruction(self, state):
        raise NotImplementedError

    def fill_device_meta(self, event):
        pass

    def fill_device_state(self, device_state):
        raise NotImplementedError

    def update_name(self, new_name):
        self.device_name = new_name
        self.config["name"] = new_name


class SimpleSensorDevice(GenericDevice):

    def __init__(self, config, devices_manager):
        super().__init__(config, devices_manager)
        self.pin = int(self.config["pin"])

    def start(self):
        super().start()
        self.devices_manager.subscribe_pin(self, self.pin)

    def stop(self):
        self.devices_manager.unsubscribe_pin(self, self.pin)
        super().stop()

    def device_id(self):
        return "{}-{}-pin-{}".format(self.__class__.__name__, getnode(),
                                     self.pin)

    def fill_device_meta(self, event):
        pass

    def fill_device_state(self, device_state):
        pass

    def on_change(self, pin, value):
        pass

    def get_config(self):
        obj = super().get_config()
        obj["pin"] = self.pin
        return obj

    @staticmethod
    def new_config():
        return {
            "name": "New Simple Sensor Device",
            "pin": 0,
            "kind": SimpleSensorDevice.__name__
        }


class MotionSensorDevice(SimpleSensorDevice):

    def fill_device_meta(self, event):
        event.kind = DeviceKind.DEVICE_KIND_MOTION_SENSOR
        event.capabilities.sensor.supports_motion_sensor = True

    def on_change(self, pin, value):
        msg = DeviceState(device_id=self.device_id())
        msg.motion_sensor_event = (MotionSensorState.MOTION_DETECTED
                                   if value == PinValue.PIN_VALUE_HIGH else
                                   MotionSensorState.NO_MOTION)
        self.devices_manager.send_event(msg)

    @staticmethod
    def new_config():
        config = super(MotionSensorDevice, MotionSensorDevice).new_config()
        config["kind"] = MotionSensorDevice.__name__
        return config


class SimpleActuatorDevice(GenericDevice):

    def __init__(self, config, devices_manager):
        super().__init__(config, devices_manager)
        self.pin = int(self.config["pin"])

    def device_id(self):
        return "{}-{}-pin-{}".format(self.__class__.__name__, getnode(),
                                     self.pin)

    def fill_device_meta(self, event):
        event.kind = DeviceKind.DEVICE_KIND_GENERIC_ACTUATOR
        event.capabilities.power_state.supported_power_states[:] = [
            PowerState.POWER_STATE_OFF, PowerState.POWER_STATE_ON
        ]

    def fill_device_state(self, device_state):
        pass

    def on_instruction(self, state):
        if state.power_state == PowerState.POWER_STATE_ON:
            self.devices_manager.set_pin(self, self.pin, 1)
        elif state.power_state == PowerState.POWER_STATE_OFF:
            self.devices_manager.set_pin(self, self.pin, 0)

    def get_config(self):
        obj = super().get_config()
        obj["pin"] = self.pin
        return obj

    @staticmethod
    def new_config():
        return {
            "name": "New Simple Actuator Device",
            "pin": 0,
            "kind": SimpleActuatorDevice.__name__
        }


KNOWN_DEVICE_TYPES = {
    "MotionSensorDevice": {
        "kind": DeviceKind.DEVICE_KIND_MOTION_SENSOR,
        "default_name": "Motion Sensor",
        "cls": MotionSensorDevice
    },
    "SimpleSensorDevice": {
        "cls": SimpleSensorDevice,
        "default_name": "Simple Sensor Device"
    },
    "SimpleActuatorDevice": {
        "cls": SimpleActuatorDevice,
        "default_name": "Simple Actuator Device",
    }
}

DEVICE_KINDS = {
    value["kind"]: key
    for key, value in KNOWN_DEVICE_TYPES.items() if "kind" in value
}


def str_to_device_kind(val):
    res = KNOWN_DEVICE_TYPES.get(val, None)
    if not res:
        return DeviceKind.DEVICE_KIND_UNKNOWN
    return res.get("kind", DeviceKind.DEVICE_KIND_UNKNOWN)


def device_kind_to_str(device_kind):
    res = DEVICE_KINDS.get(device_kind, None)
    if res is None or device_kind == DeviceKind.DEVICE_KIND_UNKNOWN:
        return "GenericGPIODevice"
    return res


def get_device_class(type_str):
    try:
        return KNOWN_DEVICE_TYPES[type_str]["cls"]
    except:
        raise BadArguments(type_str)
