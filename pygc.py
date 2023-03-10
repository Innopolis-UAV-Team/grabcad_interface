import argparse
import functools
import os
import re
from datetime import datetime
from typing import Tuple, Callable, TypeAlias, ParamSpec

import keyring

from api import GrabCadAPI
from entities.exceptions import NotAuthenticatedError, InvalidProjectUrl
from filesystem import Filesystem
from keyring_manager import CredManager
from state import State

APP_ID = 'PyGC'


P = ParamSpec('P')
CredFunction: TypeAlias = Callable[[P.kwargs], Tuple[str, str]]


def _manage_creds(func: CredFunction) -> CredFunction:
    """
    Decorator that manages credentials:
        - If present, accepts creds given as arguments to the function.
        - Saves them into the keyring if necessary
        - Or fetches them from the keyring, if
    :param func: function to be decorated
    :return:
    """
    @functools.wraps(func)
    def inner(**kwargs: P.kwargs) -> Tuple[str, str]:
        email = kwargs['email']
        password = kwargs['password']
        no_save = kwargs['no_save']
        m = CredManager(email=email, password=password, no_save=no_save)
        kwargs['email'], kwargs['password'] = m.get_creds()
        return func(**kwargs)
    return inner


def init(name: str, **kwargs):
    if os.path.exists(name):
        print(f'Folder {name} already exists. Leaving')
        return

    os.mkdir(name)
    with State(state_dir=os.path.join(os.getcwd(), name)) as state:
        pass
    print(f"Successfully initialized empty GrabCAD repo {name}")


@_manage_creds
def login(email: str, password: str, **kwargs):
    GrabCadAPI(email, password, './')


@_manage_creds
def pull(email: str, password: str, force: bool, quiet: bool, **kwargs):
    with State(state_dir=os.getcwd()) as state:
        api = GrabCadAPI(email, password, os.getcwd())
        api.load_defaults_from_state(state)
        filesystem = Filesystem(state=state, api=api)
        last_commit = state.last_local_commit()
        commits = api.get_commits_since(
            last_commit.created_at if last_commit is not None else
            datetime.fromtimestamp(1000000))

        # TODO fix non-force pull eating changes to locally-changed files
        commits = state.diff(commits)[1]
        f = filesystem.pull(commits, force=force, quiet=quiet)


@_manage_creds
def clone(url: str, email: str, password: str, **kwargs):
    project_id = re.search(r'projects/(.*)\??#/', url).group(1)
    if project_id is None:
        raise InvalidProjectUrl(url)
    api = GrabCadAPI(email, password, './')
    project = api.get_project_info(project_id)
    api.default_project = project
    root_folder = api.get_folder_info(project.root_folder_id)[0]

    if os.path.exists(root_folder.filename):
        print(f'Folder {root_folder.filename} already exists. Trying to pull')
        os.chdir(root_folder.filename)
        pull(email=email, password=password, **kwargs)
        return

    os.mkdir(root_folder.filename)

    with State(state_dir=os.path.join(os.getcwd(), root_folder.filename)) as state:
        state.project = project
        state.organisation = project.org
        print(f'Successfully initialized GrabCAD repo {project.name}')
    os.chdir(root_folder.filename)
    pull(email=email, password=password, **kwargs)


parser = argparse.ArgumentParser()
subparsers = parser.add_subparsers()

login_parent_parser = argparse.ArgumentParser(add_help=False)
login_parent_parser.add_argument(
    '--email', help='your GrabCad email', required=False, dest='email')
login_parent_parser.add_argument(
    '--pass', help='your GrabCad password', required=False, dest='password')
login_parent_parser.add_argument(
    '--dont_save_creds', help='prevent saving your credentials to keyring',
    required=False, default=False, dest='no_save', type=bool)


login_parser = subparsers.add_parser(
    'login', help='log into GrabCad account')
login_parser.add_argument(
    '--email', help='your GrabCad email', required=True, dest='email')
login_parser.add_argument(
    '--pass', help='your GrabCad password', required=True, dest='password')
login_parser.set_defaults(func=login)

init_parser = subparsers.add_parser(
    'init', help='initialize new GrabCad repo', parents=[login_parent_parser])
init_parser.add_argument(
    '--name', help='repo name to create', dest='name', required=True)
init_parser.set_defaults(func=init)


clone_parser = subparsers.add_parser(
    'clone', help='Clone GrabCad repo', parents=[login_parent_parser])
clone_parser.add_argument(
    '--url', help='project url', dest='url', required=True)
clone_parser.set_defaults(func=clone)
clone_parser.add_argument(
    '--force', default=False, type=bool,
    help='overwrite local changes forcibly', dest='force')
clone_parser.add_argument(
    '--quiet', default=False, type=bool,
    help='supress downloader messages', dest='quiet')


pull_parser = subparsers.add_parser(
    'pull', help='integrate remote changes', parents=[login_parent_parser])
pull_parser.add_argument(
    '--force', default=False, type=bool,
    help='overwrite local changes forcibly', dest='force')
pull_parser.add_argument(
    '--quiet', default=False, type=bool,
    help='supress downloader messages', dest='quiet')

pull_parser.set_defaults(func=pull)
args = parser.parse_args()
args.func(**vars(parser.parse_args()))
