from typing import List
from .syllable import Syllable, SyllableConnection


class Sentence:
    def __init__(self,
                 syllables: List[Syllable]):
        self.syllables = syllables

    def text(self, with_drop_capital=True):
        t = ''
        for syllable in self.syllables:
            text = syllable.text
            if not with_drop_capital and syllable.drop_capital_length > 0:
                text = text[syllable.drop_capital_length:]

            if syllable.connection == SyllableConnection.NEW:
                if len(t) == 0:
                    t += text
                else:
                    t += ' ' + text
            elif syllable.connection == SyllableConnection.VISIBLE:
                t += '~' + text
            else:
                t += '-' + text
        return t

    def syllable_by_id(self, syllable_id):
        for s in self.syllables:
            if s.id == syllable_id:
                return s

        return None

    @staticmethod
    def from_json(json: list):
        return Sentence(
            [Syllable.from_json(s) for s in json]
        )

    def to_json(self):
        return [s.to_json() for s in self.syllables]

