import asyncio
import dataclasses
import hashlib
import os
from dataclasses import dataclass, field
from typing import List, TypeVar, Tuple

from api import GrabCadAPI
from entities.files import LocalFile, File, FileShort, BaseNode, LocalFileShort, DigestNode
from entities.grabcad import Change, Commit, FileType, ChangeCode
from state import State
import glob


@dataclass
class Filesystem:
    state: State = field(repr=False)
    api: GrabCadAPI = field(repr=False)

    @property
    def local_file_list(self) -> List[LocalFileShort]:
        return [
            LocalFileShort(
                filename=os.path.split(file)[1],
                path=os.path.split(file)[0]
            ) for file in glob.glob(
                os.path.join(self.api.root_folder, '**'), recursive=True
            ) if os.path.isfile(file)
        ]

    @staticmethod
    def file_changes(commits: List[Commit]) -> Tuple[List[FileType], List[FileType]]:
        """
        Returns latest file changes and delitions for list of commits `commits`
        :param commits:
        :return:
        """
        changed_files = {}
        for commit in commits:
            for change in commit.changes:
                if (
                        change.file.item_id in changed_files and
                        change.file.last_version > changed_files[change.file.item_id].file.last_version
                        or change.file.item_id not in changed_files):
                    changed_files[change.file.item_id] = change

        changed = [x.file for x in changed_files.values() if x.change_code != ChangeCode.DELETED]
        deleted = [x.file for x in changed_files.values() if x.change_code == ChangeCode.DELETED]
        return changed, deleted

    def pull(self, commits: List[Commit], force: bool = False, quiet: bool = False, batch_size: int = 50) -> List[LocalFile]:
        # use file digest as a key to find which files were changed
        local_files = {
            x.digest: x for x in self.local_file_list
        }
        # find local files that are in commit history
        local_committed_files = {
            x.digest: x for x in Filesystem.file_changes(self.state.local_commits)[0]
        }

        # find last versions of each file, if it is missing in local FS
        # like if it was added and then deleted, _remove_changes will handle that
        remote_update, remote_delete = Filesystem.file_changes(commits)
        self._remove_files(remote_delete, quiet)

        # pull the download info for each updating file
        remote_update = self.api.loop.run_until_complete(
            asyncio.gather(*[File.from_short_file(file, self.api) for file in remote_update])
        )

        # find non-committed local changes and check if they will be overwritten
        local_changes = {
            local_files[k].filename: local_files[k]
            for k in local_files.keys() - local_committed_files.keys()
        }
        overwriting_changes = {
            file.filename: file for file in remote_update if file.filename in local_changes
        }

        # Construct a list of files to be downloaded, taking overwriting into account
        files_to_download = [
            file for file in remote_update if
            force or not (file.filename in overwriting_changes and
                os.path.normpath(file.full_path) == os.path.normpath(overwriting_changes[file.filename].full_path))
        ]

        batches = [
            files_to_download[x:x + batch_size]
            for x in range(0, len(files_to_download), batch_size)
        ]

        for batch in batches:
            self.api.download_files(batch)

            if not quiet:
                print(f'Downloaded: {os.linesep.join([file.filename for file in batch])}')

        for commit in commits:
            for change in commit.changes:
                change.file = LocalFile(
                    **dataclasses.asdict(change.file),
                    version_list={}, root_directory=self.api.root_folder
                )
        commits.sort(key=lambda k: k.created_at)
        self.state.local_commits.extend(commits)
        not_downloaded = list(overwriting_changes.values()) if not force else []

        if not quiet:
            print(f'Local changes exist: {os.linesep.join([file.filename for file in not_downloaded])}')
        return not_downloaded

    def _remove_files(self, files: List[FileShort], quiet: bool):
        for file in files:
            dir_path = os.path.join(self.api.root_folder, file.path_without_root_folder)
            path = os.path.join(dir_path, file.filename)
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            # GrabCAD has no special commit for removing directories, so let's
            # clean up any empty dirs left after
            try:
                os.rmdir(dir_path)
            except OSError:
                pass

        if not quiet:
            print(f'Removed files: {os.linesep.join([file.filename for file in files])}')
