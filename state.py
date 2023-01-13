from __future__ import annotations

import os
import pickle
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

from entities.grabcad import Commit, Project, Organisation


@dataclass
class State:
    local_commits: List[Commit] = field(default_factory=list)
    project: Project = field(default=None)
    organisation: Organisation = field(default=None)
    state_dir: str = field(default='./')
    _default_state_file: str = field(init=False, default='.pygrabcad')

    @property
    def state_file(self) -> str:
        return os.path.join(self.state_dir, self._default_state_file)

    def save(self):
        """
        Save repository state to disk
        :return:
        """
        data = pickle.dumps([self.local_commits, self.project, self.organisation])
        with open(self.state_file, 'wb') as file:
            file.write(data)

    def __enter__(self) -> State:
        if not os.path.isfile(self.state_file):
            with open(self.state_file, 'wb') as file:
                file.write(pickle.dumps([[], None, None]))
        with open(self.state_file, 'rb') as file:
            commits, project, org = pickle.loads(file.read())
            self.local_commits = commits
            self.project = project
            self.organisation = org
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.save()

    def diff(self, other: List[Commit]) -> Tuple[List[Commit], List[Commit]]:
        """
        Returns commit difference between local and remote
        :param other: remote commit list
        :return: 2-tuple, where the 1st element contains commits present in local folder and not in remote
        The 2nd element contains commits present in remote but not in local folder
        """
        commit_dict_local = {x.commit_id: x for x in self.local_commits}
        commit_dict_remote = {x.commit_id: x for x in other}

        local_not_in_remote = [
            commit_dict_local[k]
            for k in (commit_dict_local.keys() - commit_dict_remote.keys())
        ]
        remote_not_in_local = [
            commit_dict_remote[k]
            for k in (commit_dict_remote.keys() - commit_dict_local.keys())
        ]

        return local_not_in_remote, remote_not_in_local

    def last_local_commit(self) -> Optional[Commit]:
        """
        Returns last local commit, if exists
        :return:
        """
        if self.local_commits:
            return self.local_commits[-1]
        else:
            return None

