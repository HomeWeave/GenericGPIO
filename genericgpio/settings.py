import json
from pathlib import Path

DEFAULT_SETTINGS_OBJ = {"devices": []}


def write_settings(path, settings):
    with path.open(mode='w') as out:
        json.dump(settings, out)


class Settings:

    def __init__(self, data_dir, write_callback=None):
        self.file = Path(data_dir) / 'settings.json'
        self.write_callback = write_callback

        if not self.file.is_file():
            write_settings(self.file, DEFAULT_SETTINGS_OBJ)

        with self.file.open() as f:
            self.props = json.load(f)

    def get_prop(self, key, default=None):
        return self.props.get(key, default)

    def set_prop(self, key, value):
        self.props[key] = value
        write_settings(self.file, self.props)
        if self.write_callback:
            self.write_callback(self.props)
