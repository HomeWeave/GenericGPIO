import json
import base64
from pathlib import Path

from google.protobuf import json_format
from google.protobuf import text_format

from anton.settings_pb2 import SettingsResponse
from anton.ui_pb2 import Page, CustomMessage

DEFAULT_SETTINGS_OBJ = {"devices": []}


def write_settings(path, settings):
  with path.open(mode='w') as out:
    json.dump(settings, out)


class Settings:

  def __init__(self, data_dir):
    self.file = Path(data_dir) / 'settings.json'

    if not self.file.is_file():
      write_settings(self.file, DEFAULT_SETTINGS_OBJ)

    with self.file.open() as f:
      self.props = json.load(f)

  def get_prop(self, key, default=None):
    return self.props.get(key, default)

  def set_prop(self, key, value):
    self.props[key] = value
    write_settings(self.file, self.props)

  def flush(self):
    write_settings(self.file, self.props)
