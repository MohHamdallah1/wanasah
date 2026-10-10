"""Safe operator errors: never include SQL parameters, hashes or connection URLs."""


class BackfillError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)
