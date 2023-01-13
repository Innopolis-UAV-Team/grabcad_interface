from __future__ import annotations
import asyncio
import datetime
import math
import os.path
from asyncio import AbstractEventLoop
from typing import List, Tuple, TypeVar, Union
from urllib.parse import unquote

from async_lru import alru_cache
from dateutil import parser
from httpx import AsyncClient
from lxml import html as tree
from lxml.html import HtmlElement

from entities.exceptions import AuthError, ProjectNotSet, OrganisationNotSet, \
    RepoNotInitialized
from entities.files import FileShort, File, Folder, Triplet
from entities.grabcad import Project, Organisation, User, UserWithRole, \
    UserRole, Commit, Change, ChangeCode
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from state import State


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


class GrabCadAPI(metaclass=Singleton):
    client: AsyncClient
    loop: AbstractEventLoop
    root_folder: str
    default_organisation: Organisation
    default_project: Project
    me: User
    _COMMIT_LIST_URL = 'https://workbench.grabcad.com/workbench/projects/{}/events'
    _COMMIT_URL = 'https://workbench.grabcad.com/workbench/projects/{}/events/{}'
    _ORGANISATIONS_URL = 'https://workbench.grabcad.com/workbench/myprojects/load_accounts'
    _PROJECT_MEMBERS_URL = 'https://workbench.grabcad.com/workbench/projects/{}/collaborators'
    _PROJECT_INFO_URL = 'https://workbench.grabcad.com/workbench/projects/{}/load_project_data'
    _ORGANISATION_MEMBERS_URL = 'https://workbench.grabcad.com/accounts/{}/account_members'
    _ORGANISATION_PROJECTS_URL = 'https://workbench.grabcad.com/workbench/myprojects/{}/workbench_projects'
    _PROJECT_FILE_URL = 'https://workbench.grabcad.com/workbench/projects/{}/files/{}'
    _PROJECT_FOLDER_URL = 'https://workbench.grabcad.com/workbench/projects/{}/folders/{}'
    _UPLOAD_SESSION_URL = 'https://workbench.grabcad.com/workbench/projects/{}/uploads/create_upload_session'
    _UPLOAD_NAME_CHECK_URL = 'https://workbench.grabcad.com/workbench/projects/{}/check_file_name'
    _UPLOAD_GET_DATA = 'https://workbench.grabcad.com/workbench/projects/{}/uploads/file_upload_data'
    _UPLOAD_CONFIRM_URL = 'https://workbench.grabcad.com/workbench/projects/{}/confirm_upload_files'

    def __init__(self, email: str, password: str, root_folder: str):
        self.root_folder = os.path.abspath(root_folder)
        self.loop = asyncio.get_event_loop()
        asyncio.set_event_loop(self.loop)
        self.client = AsyncClient()
        login_page_data: HtmlElement = self.loop.run_until_complete(
            self.client.request('GET', 'https://workbench.grabcad.com/login')).text
        login_page = tree.fromstring(login_page_data)

        # login
        csrf = login_page.xpath('//*[@name="csrf-token"]/@content')[0]
        f = self.loop.run_until_complete(self.client.post(
            'https://workbench.grabcad.com/community/login', json={
                "format": "json",
                "member": {
                    "email": email,
                    "password": password,
                    "authenticity_token": csrf
                }
            }, headers={'X-XSRF-TOKEN': unquote(self.client.cookies['XSRF-TOKEN'])}))
        if f.status_code != 200:
            raise AuthError(f.status_code)

    PRJ = TypeVar('PRJ', bound=Union[str, Project])

    def _active_project(self, proj: PRJ) -> PRJ:
        """
        Returns active project, either supplied as argument, or from api's default_project
        :param proj:
        :return:
        """
        if proj:
            return proj
        if self.default_project is not None:
            if isinstance(proj, str):
                return self.default_project.project_id
            else:
                return self.default_project
        raise ProjectNotSet()

    ORG = TypeVar('ORG', bound=Union[int, Organisation])

    def _active_organisation(self, org: ORG) -> ORG:
        """
        Returns active organisation, either supplied as argument, or from api's default_organisation
        :param org:
        :return:
        """
        if org:
            return org
        if self.default_organisation is not None:
            if isinstance(org, str):
                return self.default_organisation.org_id
            else:
                return self.default_organisation
        raise OrganisationNotSet()

    @alru_cache
    async def get_file_info(self, file_id: int, project_id: str = "") -> File:
        """
        Gets information about this file from GrabCAD server
        :param file_id:
        :param project_id:
        :return:
        """
        project_id = self._active_project(project_id)

        file_data = (await self.client.get(
            self._PROJECT_FILE_URL.format(project_id, file_id)))
        file_data = file_data.json()
        return File(
            root_directory=self.root_folder,
            item_id=file_data["id"],
            filename=file_data["name"],
            last_version=file_data["version"],
            path=os.path.sep.join([x["name"] for x in file_data["directory_path"]]),
            last_update=parser.parse(file_data["updated_at"]),
            version_list={
                x["version_number"]: x["url"] for x in file_data["versions"]
            }
        )

    @alru_cache
    async def get_folder_info(self, folder_id: int, project_id: str = "") -> Tuple[Folder, List[Triplet]]:
        """
        Gets information about this folder from GrabCAD server
        :param folder_id:
        :param project_id:
        :return:
        """
        project_id = self._active_project(project_id)

        folder_data = (await self.client.get(
            self._PROJECT_FOLDER_URL.format(project_id, folder_id))).json()['node']
        return Folder(
            item_id=folder_data["id"],
            filename=folder_data["label"],
            path=os.path.sep.join([x["name"] for x in folder_data["directory_path"]]),
            last_update=parser.parse(folder_data["updated_at"]),
            children=[]
        ), [Triplet(
            item_id=x["id"],
            type=x["filetype"]
        ) for x in folder_data['children']]

    def get_commits_since(self, time: datetime.datetime, project: Project = None) -> List[Commit]:
        project = self._active_project(project)
        last_commit = math.inf
        commits = []
        last_len = -1
        # Fetch commits sequentially before getting to ones that are earlier than `time`
        while last_commit > time.timestamp() and last_len != len(commits):
            commits_json = self.loop.run_until_complete(self.client.get(
                self._COMMIT_LIST_URL.format(project.project_id),
                params={"until": last_commit} if commits else {})).json()
            # ignore all non-commit events
            commits_json = [x.json() for x in self.loop.run_until_complete(
                asyncio.gather(*[
                    self.client.get(
                        self._COMMIT_URL.format(self.default_project.project_id, x['id'])
                    ) for x in commits_json if x["type"] == "snapshot_created"]
                )
            )]

            # assemble list of commits
            last_len = len(commits)
            commits.extend([
                Commit(
                    commit_id=x["id"],
                    name=x["snapshot"]["name"],
                    message=x["message"],
                    author=User(
                        user_id=x["author"]["id"],
                        username=x["author"]["name"],
                        email=None),
                    created_at=datetime.datetime.fromtimestamp(x["exact_time"]),
                    changes=[Change(
                        file=FileShort(
                            item_id=k["id"],
                            filename=k["name"],
                            path=k["path"],
                            last_version=k["version"],
                            last_update=datetime.datetime.fromtimestamp(x["exact_time"])
                        ),
                        # find the correct change code (add / update / remove)
                        change_code=next(filter(
                            lambda x: x[1],
                            zip(ChangeCode, [k['added'], k['updated'] or k['moved'] or k['renamed'], k['deleted']])
                        ))[0]
                    ) for k in x["snapshot"]["changes"]]
                ) for x in commits_json
            ])
            last_commit = commits[-1].created_at.timestamp()

        # API returns commits in tens, so there might be more than we need
        commits = [x for x in commits if x.created_at >= time]
        return commits

    @staticmethod
    def update_organisation_members(org: Organisation, members: List[UserWithRole]):
        for user in members:
            if user.role == UserRole.Admin:
                org.owner = user
            else:
                org.members.append(user)

    def get_organisations(self) -> List[Organisation]:
        orgs_json = self.loop.run_until_complete(self.client.get(self._ORGANISATIONS_URL)).json()

        orgs = [
            Organisation(
                org_id=x["id"],
                name=x["name"],
                owner=None,
                members=[]
            ) for x in orgs_json["accounts"]]

        # Fetch user info for organisation members
        for org in orgs:
            users = self.get_organisation_members(org)
            self.update_organisation_members(org, users)
        return orgs

    def load_defaults_from_state(self, state: State):
        if not any([state.project, state.organisation]):
            raise RepoNotInitialized()
        self.load_default_project(state.project)
        self.load_default_organisation(state.organisation)

    def load_default_organisation(self, org: Organisation):
        self.default_organisation = org

    def load_default_project(self, proj: Project):
        self.default_project = proj

    def get_project_members(self, project: Project = None) -> List[UserWithRole]:
        project = self._active_project(project)
        users = self.loop.run_until_complete(self.client.get(
            self._PROJECT_MEMBERS_URL.format(project.project_id)
        )).json()["collaborators"]

        return [UserWithRole(
            user_id=x["id"],
            username=x["name"],
            email=x["email"],
            role=UserRole(x["role_id"]),
            organisations=None
        ) for x in users]

    def get_organisation_members(self, org: Organisation = None) -> List[UserWithRole]:
        org = self._active_organisation(org)
        users = self.loop.run_until_complete(self.client.post(
            self._ORGANISATION_MEMBERS_URL.format(org.org_id),
            headers={'X-XSRF-TOKEN': unquote(self.client.cookies['XSRF-TOKEN'])}
        )).json()["visible_account_members"]

        return [UserWithRole(
            user_id=x["id"],
            username=x["name"],
            email=x["email"],
            role=UserRole(x["role"]) if not x["admin"] else UserRole.Admin,
            organisations=None
        ) for x in users]

    def get_organisation_projects(self, org: Organisation = None) -> List[Project]:
        org = self._active_organisation(org)
        data = self.loop.run_until_complete(
            self.client.get(self._ORGANISATION_PROJECTS_URL.format(org.org_id))).json()
        projects = [
            Project(
                project_id=x["id"],
                description=x["description"],
                name=x["name"],
                last_update=parser.parse(x["updated_at"]),
                members=[],
                org=org,
                root_folder_id=x["root_folder_id"]
            ) for x in data["projects"]
        ]

        for project in projects:
            project.members = self.get_project_members(project)
        return projects

    def get_project_info(self, project_id: str) -> Project:
        data = self.loop.run_until_complete(
            self.client.get(self._PROJECT_INFO_URL.format(project_id))
        ).json()

        org = Organisation(
            org_id=data['account']['id'],
            name=data['account']['name'],
        )
        self.update_organisation_members(org, self.get_organisation_members(org))

        project = Project(
            project_id=data["id"],
            description=data["description"],
            name=data["name"],
            last_update=parser.parse(data["updated_at"]),
            members=[],
            org=org,
            root_folder_id=data["root_folder_id"]
        )
        project.members = self.get_project_members(project)
        return project

    def get_project_tree(self, project: Project = None) -> Folder:
        """
        Fetch filesystem structure of `project`
        :param project:
        :return: Folder object with children (grandchildren and so on) representing the filesystem of project
        """
        project = self._active_project(project)
        root_folder, children = self.loop.run_until_complete(
            Folder.fetch(project.root_folder_id, self))
        # fetch root directory children
        to_visit = [(root_folder, x) for x in children]

        async def fetch_children(parent: Folder, child: Triplet,
                                 buffer: List[Tuple[Folder, Triplet]], api: GrabCadAPI):
            # result is either File or 2-tuple of Folder and it's children - list of Triplets
            # add children to buffer to be processed later
            node = await child.get(api)
            if isinstance(node, File):
                parent.children.append(node)
            else:
                node, children = node
                buffer.extend([(node, x) for x in children])

        # run BFS here
        while to_visit:
            buff = []
            self.loop.run_until_complete(asyncio.gather(*[
                fetch_children(parent_node, child_node, buff, self) for parent_node, child_node in to_visit
            ]))
            to_visit = buff
        return root_folder

    def download_files(self, files: List[File]):
        """
        Download and save to disk file in `files`, in parallel
        :param files: files to be downloaded
        :return:
        """
        async def download_file(file: File, api: GrabCadAPI):
            link = file.version_list[file.last_version]
            data = await api.client.get(link)
            path = os.path.join(api.root_folder, file.path_without_root_folder)
            os.makedirs(path, exist_ok=True)
            file.save(data.content)
        # use async inner function to achieve parallelism
        self.loop.run_until_complete(
            asyncio.gather(*[download_file(file, self) for file in files])
        )

    def upload_files(self, files: List[File], commit_message: str, project: Project = None):
        """
        Pushes new commit, uploading list of files
        :param files: files to be pushed
        :param commit_message:
        :param project: project for which commit is created. Can be empty.
        :return:
        """
        project = self._active_project(project)
        # Here is the drill
        # - upload session is created, with its upload_session_id
        # - ability to push is evaluated
        # - upload link is fetched
        # - file is uploaded
        # - upload is confirmed

        # - session creation
        upload_session_id = self.loop.run_until_complete(
            self.client.post(
                self._UPLOAD_SESSION_URL.format(project.project_id),
                json={'folder_id': project.root_folder_id},
                headers={'X-XSRF-TOKEN': unquote(self.client.cookies['XSRF-TOKEN'])}
            )
        ).json()['upload_session_id']

        # evaluate ability to push
        check_files = self.loop.run_until_complete(
            self.client.post(
                self._UPLOAD_NAME_CHECK_URL.format(project.project_id),
                json={
                    'files': [{
                        'file_name': file.filename,
                        'folder_id': project.root_folder_id,
                        'relative_path': file.path
                    } for file in files]},
                headers={'X-XSRF-TOKEN': unquote(self.client.cookies['XSRF-TOKEN'])}
            )
        ).json()
        uploads = []

        async def get_upload_data(file: File, api: GrabCadAPI):
            upload_url = (await api.client.post(
                    self._UPLOAD_GET_DATA.format(project.project_id),
                    json={
                        'format': 'js',
                        'batch_id': upload_session_id,
                        'folder_id': project.root_folder_id,
                        'file_type': file.extension.strip('.'),
                        'relative_path': file.path,
                        'file_id': 'HTML_Upload_1',
                        'file_file_name': file.filename,
                        'intelligent_tiering': True,
                        'upload_method': 'html'
                    },
                    headers={'X-XSRF-TOKEN': unquote(api.client.cookies['XSRF-TOKEN'])}
                )
            ).json()['url']
            uploads.append([file, upload_url])

        # fetch data needed for upload (link, mainly)
        self.loop.run_until_complete(asyncio.gather(*[
            get_upload_data(file, self) for file, check in zip(files, check_files)
            if not check['exists'] or check['has_access'] and check['can_overwrite'] and not check['lock']['locked']]
        ))

        # upload
        # it can be done more efficiently with list comp, but this approach also works.
        self.loop.run_until_complete(asyncio.gather(*[
                self.client.post(
                    url, data=file.load(),
                    headers={
                        'X-XSRF-TOKEN': unquote(self.client.cookies['XSRF-TOKEN']),
                        'content-type': 'application/octet-stream'}
                ) for file, url in uploads]
        ))

        # finalize the commit by confirming the upload
        self.loop.run_until_complete(
            self.client.post(
                self._UPLOAD_CONFIRM_URL.format(project.project_id),
                params={'project_id': project.project_id},
                data={
                    'format': 'js',
                    'batch_id': upload_session_id,
                    'description': commit_message,
                    'unlock_files_after_upload': False,
                    'notify_of_upload': True,
                    's3_upload_count': len(uploads),
                    'error_count': 0
                },
                headers={'X-XSRF-TOKEN': unquote(self.client.cookies['XSRF-TOKEN'])},
            ),
        )