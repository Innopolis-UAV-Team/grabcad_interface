from __future__ import annotations

import hashlib
import os.path
import re
import typing
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Tuple, Dict, BinaryIO

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

    file: BinaryIO = field(default=None, init=False)
    size: int = field(default=0)

    @staticmethod
    async def from_short_file(file: FileShort, api: GrabCadAPI) -> File:
        return await api.a_get_file_info(file.item_id)

    @staticmethod
    async def fetch(file_id: int, api: GrabCadAPI) -> File:
        return await api.a_get_file_info(file_id)

    def load(self) -> bytes:
        with self:
            return self.file.read()

    def save(self, data: bytes):
        with self:
            return self.file.write(data)

    def __enter__(self):
        self.file = open(self.full_path, 'wb')

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.file.close()

    def save_chunk(self, data: bytes):
        self.file.write(data)

    @property
    def full_path(self) -> str:
        """
        full path to this file, mainly used in filesystem operations
        :return:
        """
        return os.path.join(
            self.root_directory, self.path_without_root_folder, self.filename)


@dataclass
class BatchDownloadProgress:
    """
    Keeps, updates and reports the download progress of multiple FileDownloadProgress
    """
    expected_batch_size: int = field(default=20)
    increment: int = field(default=10)
    quiet: bool = field(default=False)

    downloads: Dict[str, FileDownloadProgress] = field(init=False, default_factory=dict)
    _last_progress: int = field(init=False, default = 0)

    _is_first_render: int = field(init=False, default=True)
    _total_downloaded: int = field(init=False, default=0)
    _total_size: int = field(init=False, default=0)

    @property
    def overall_progress(self) -> int:
        return int(self._total_downloaded/self._total_size * 100)

    def add(self, value: FileDownloadProgress):
        self.downloads[value.file.filename] = value
        self._total_size += value.size

    def __getitem__(self, item: FsNode) -> FileDownloadProgress:
        return self.downloads[item.filename]

    def update_progress(self, file: FsNode, downloaded: int):
        self[file].downloaded += downloaded
        self._total_downloaded += downloaded

    def render(self):
        # print nothing if the batcher is not full yet to prevent clutter in CLI
        if len(self.downloads) < self.expected_batch_size:
            return
        if self.quiet:
            return
        if self._is_first_render:
            print('Downloading files:')
            print('\n'.join([f'{x.file.filename}: {x.size}' for x in self.downloads.values()]))
            self._last_progress = self.overall_progress
            self._is_first_render = False
        # print only in 10 percent increments
        elif self.overall_progress - self._last_progress > self.increment:
            self._last_progress = self.overall_progress
            print(' '.join([f'{x.progress}%' for x in self.downloads.values()]))


@dataclass
class FileDownloadProgress:
    """
    Keeps download progress of one FsNode
    """
    file: FsNode
    size: int
    downloaded: int = field(default=0)

    @property
    def progress(self) -> int:
        return int((self.downloaded/self.size)*100) if self.size else 100


@dataclass
class Folder(FsNode, RemoteNode):
    children: List[FsNode]

    @classmethod
    async def fetch(cls, folder_id: int, api: GrabCadAPI) -> Tuple[Folder, List[Triplet]]:
        return await api.a_get_folder_info(folder_id)


@dataclass
class DigestNode:
    digest: str = field(default='')
    size: int = field(default=0)

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
        try:
            self.size = os.path.getsize(self.full_path)
        except FileNotFoundError:
            self.size = 0


@dataclass
class LocalFile(DigestNode, File):
    pass


@dataclass
class LocalFileShort(DigestNode, BaseNode):
    pass
