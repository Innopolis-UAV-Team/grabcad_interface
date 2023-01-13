import argparse
import functools
import os
import re
from datetime import datetime
from typing import Tuple, Callable, TypeAlias, ParamSpec

import keyring

from api import GrabCadAPI
from entities.exceptions import NotAuthenticatedError, InvalidProjectUrl, \
    RepoNotInitialized
from filesystem import Filesystem
from state import State

APP_ID = 'PyGC'


def initialize(email: str, password: str) -> Tuple[GrabCadAPI, State, Filesystem]:
    directory = os.path.dirname(os.path.realpath(__file__))
    print(directory)
    api = GrabCadAPI(email, password, directory)
    state = State.load()
    filesystem = Filesystem(state=state, api=api)
    return api, state, filesystem


def _fetch_creds_keyring() -> Tuple[str, str]:
    password = keyring.get_password(APP_ID, 'password')
    email = keyring.get_password(APP_ID, 'email')
    if not all([password, email]):
        raise NotAuthenticatedError()
    return email, password


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
        if email and password:
            if not no_save:
                _save_creds(email, password)
            return func(**kwargs)
        else:
            kwargs['email'], kwargs['password'] = _fetch_creds_keyring()
            return func(**kwargs)
    return inner


def _save_creds(email: str, password: str):
    """
    Saves credentials to the keyring
    :param email:
    :param password:
    :return:
    """
    keyring.set_password(APP_ID, 'password', password)
    keyring.set_password(APP_ID, 'email', email)


@_manage_creds
def init(url: str, email: str, password: str, **kwargs):
    project_id = re.search(r'projects/(.*)#/', url).group(1)
    if project_id is None:
        raise InvalidProjectUrl(url)
    api = GrabCadAPI(email, password, './')
    project = api.get_project_info(project_id)
    path = os.path.join(os.getcwd(), project.name)
    os.mkdir(path)
    print(f'Initialize empty repo at {path}')
    with State(state_dir=path) as state:
        state.project = project
        state.organisation = project.org


def login(email: str, password: str, **kwargs):
    GrabCadAPI(email, password, './')
    _save_creds(email, password)


@_manage_creds
def pull(email: str, password: str, force: bool, quiet: bool, **kwargs):
    with State(state_dir=os.getcwd()) as state:
        api = GrabCadAPI(email, password, './')
        api.load_defaults_from_state(state)
        filesystem = Filesystem(state=state, api=api)
        last_commit = state.last_local_commit()
        commits = api.get_commits_since(
            last_commit.created_at if last_commit is not None else
            datetime.fromtimestamp(1000000))

        # TODO fix non-force pull eating changes to locally-changed files
        commits = state.diff(commits)[1]
        f = filesystem.pull(commits, force=force, quiet=quiet)


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
    '--url', help='project url', dest='url', required=True)
init_parser.set_defaults(func=init)

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
