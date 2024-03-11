import json
import base64
from pathlib import Path

from google.protobuf import json_format
from google.protobuf import text_format

from pyantonlib.channel import SettingsController
from anton.settings_pb2 import SettingsResponse
from anton.ui_pb2 import Page, CustomMessage


DEFAULT_SETTINGS_OBJ = {
  "devices": []
}

def write_settings(path, settings):
    with path.open(mode='w') as out:
        json.dump(settings, out)

class Settings(SettingsController):
    def __init__(self, data_dir):
        self.file = Path(data_dir) / 'settings.json'

        if not self.file.is_file():
            write_settings(self.file, DEFAULT_SETTINGS_OBJ)

        with self.file.open() as f:
            self.props = json.load(f)

        self.settings_ui_path = Path(data_dir) / 'settings_ui.json'

        super().__init__({
            "get_settings_ui": self.get_settings_ui,
            "custom_request": self.handle_custom_request
        })

    def get_prop(self, key, default=None):
        return self.props.get(key, default)

    def set_prop(self, key, value):
        self.props[key] = value
        write_settings(self.file, self.props)

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
            payload = json.dumps({"type": "settings", "payload": self.props})
        else:
            payload = None

        response = CustomMessage(index=settings_request.custom_request.index,
                                 payload=payload);
        return SettingsResponse(request_id=settings_request.request_id,
                                custom_response=response)


