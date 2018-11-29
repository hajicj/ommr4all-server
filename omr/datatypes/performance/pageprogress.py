from typing import DefaultDict
import json


class LockedStates(DefaultDict[str, bool]):
    def __init__(self):
        super().__init__(int)


class PageProgress:
    @staticmethod
    def from_json(d: dict):
        pp = PageProgress()
        for key, value in d.get('locked', {}).items():
            pp.locked[key] = bool(value)

        return pp

    def to_json(self):
        return {
            'locked': self.locked,
        }

    @staticmethod
    def from_json_file(file: str):
        return PageProgress.from_json(json.load(open(file)))

    def to_json_file(self, filename: str):
        s = json.dumps(self.to_json(), indent=2)
        with open(filename, 'w') as f:
            f.write(s)

    def __init__(self):
        self.locked = LockedStates()