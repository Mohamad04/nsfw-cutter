from dataclasses import dataclass

from schemas._validation import clean_string, validate_email


@dataclass(frozen=True)
class UserCreateSchema:
    username: str
    email: str
    password: str

    def __post_init__(self):
        object.__setattr__(self, "username", clean_string(self.username, "username", min_length=3, max_length=100, required=True))
        object.__setattr__(self, "email", validate_email(self.email))
        object.__setattr__(self, "password", clean_string(self.password, "password", required=True))
