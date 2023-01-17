from dataclasses import dataclass
from typing import Tuple

from entities.exceptions import NotAuthenticatedError

APP_ID = 'PyGC'


@dataclass
class CredManager:
    no_save: bool
    email: str
    password: str

    def get_creds(self) -> Tuple[str, str]:
        # If we do not want to use keyring and one of creds is missing - raise an Exception
        if self.no_save and not (self.email and self.password):
            raise NotAuthenticatedError()

        # If we do want to use keyring - try to store, if email and password are valid
        # If not - try to fetch
        if not self.no_save and (creds := self._fetch_from_keyring()):
            return creds

        # If creds are still invalid - raise an error
        if not all([self.password, self.email]):
            raise NotAuthenticatedError()
        return self.email, self.password

    def _fetch_from_keyring(self) -> Tuple[str, str]:
        import keyring
        if self.email and self.password:
            keyring.set_password(APP_ID, 'password', self.password)
            keyring.set_password(APP_ID, 'email', self.email)
            return self.email, self.password
        if not (self.email and self.password):
            password = keyring.get_password(APP_ID, 'password')
            email = keyring.get_password(APP_ID, 'email')
            return email, password
