from __future__ import annotations

import typing
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from enum import Enum, auto
from typing import List
from typing import Optional

from entities.files import FileShort


class UserRole(Enum):
    Admin = 1
    Collaborator = 2
    ReadOnly = 3


@dataclass
class User:
    user_id: int
    username: str
    email: Optional[str]


@dataclass
class UserWithRole(User):
    role: UserRole
    organisations: Optional[List[Organisation]]


@dataclass
class Organisation:
    org_id: int
    name: str
    owner: Optional[User] = None
    members: Optional[List[User]] = field(default_factory=list)


@dataclass
class Project:
    project_id: str
    name: str
    description: str
    org: Organisation
    last_update: datetime
    members: List[UserWithRole]
    root_folder_id: int


class ChangeCode(Enum):
    ADDED = auto()
    UPDATED = auto()
    DELETED = auto()


FileType = typing.TypeVar('FileType', bound=FileShort)


@dataclass
class Change:
    file: FileType
    change_code: ChangeCode


@dataclass
class Commit:
    commit_id: int
    name: str
    message: str
    created_at: datetime
    author: User
    changes: List[Change]