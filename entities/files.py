from __future__ import annotations

import hashlib
import os.path
import re
import typing
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Tuple, Dict

if typing.TYPE_CHECKING:
    from api import GrabCadAPI


@dataclass
class Triplet:
    item_id: int
    type: str

    async def get(self, api):
        return await File.fetch(self.item_id, api) if self.type != 'folder' \
            else await Folder.fetch(self.item_id, api)


@dataclass
class BaseNode:
    filename: str
    path: str

    @property
    def full_path(self) -> str:
        return os.path.join(self.path, self.filename)


@dataclass
class FsNode(BaseNode):
    item_id: int
    last_update: datetime


@dataclass
class FileShort(FsNode):
    last_version: int

    @property
    def name(self):
        return os.path.splitext(self.filename)[0]

    @property
    def extension(self):
        return os.path.splitext(self.filename)[1]

    @property
    def path_without_root_folder(self) -> str:
        return os.path.sep.join(re.split(r'[/\\]', self.path)[1:])


@dataclass
class RemoteNode:
    @staticmethod
    async def fetch(file_id: int, api: GrabCadAPI) -> RemoteNode:
        pass


@dataclass
class File(FileShort, RemoteNode):
    version_list: Dict[int, str]
    root_directory: str

    @staticmethod
    async def from_short_file(file: FileShort, api: GrabCadAPI) -> File:
        return await api.get_file_info(file.item_id)

    @staticmethod
    async def fetch(file_id: int, api: GrabCadAPI) -> File:
        return await api.get_file_info(file_id)

    def load(self) -> bytes:
        with open(self.full_path, 'rb') as file:
            return file.read()

    def save(self, data: bytes):
        with open(self.full_path, 'wb') as file:
            return file.write(data)


    @property
    def full_path(self) -> str:
        """
        full path to this file, mainly used in filesystem operations
        :return:
        """
        return os.path.join(
            self.root_directory, self.path_without_root_folder, self.filename)


@dataclass
class Folder(FsNode, RemoteNode):
    children: List[FsNode]

    @classmethod
    async def fetch(cls, folder_id: int, api: GrabCadAPI) -> Tuple[Folder, List[Triplet]]:
        return await api.get_folder_info(folder_id)


@dataclass
class DigestNode:
    digest: str = field(default='')

    @staticmethod
    def _file_digest(file: BaseNode, buf_size=65536) -> str:
        md5 = hashlib.md5()
        path = file.full_path
        if not os.path.isfile(path):
            return ''

        with open(path, 'rb') as f:
            while True:
                data = f.read(buf_size)
                if not data:
                    break
                md5.update(data)
        return md5.hexdigest()

    def __post_init__(self: FsNode):
        self.digest = DigestNode._file_digest(self)


@dataclass
class LocalFile(DigestNode, File):
    pass


@dataclass
class LocalFileShort(DigestNode, BaseNode):
    pass
