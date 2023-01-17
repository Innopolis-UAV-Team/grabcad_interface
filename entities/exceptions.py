class AuthError(Exception):
    def __init__(self, code: int):
        super().__init__(f"An authentication attempt failed with code {code}")


class NotAuthenticatedError(Exception):
    def __init__(self):
        super().__init__(
            "Please authenticate yourself with `python pygc.py login --email <> --pass <>` first\n"
            "Or use --email and --pass in your command if --dont_save_creds is set to True")


class ProjectNotSet(Exception):
    def __init__(self):
        super().__init__(
            "The project was not set. Either set it using GrabCadAPI.add_default_project() call"
            "or pass explicitly to the corresponding method")


class OrganisationNotSet(Exception):
    def __init__(self):
        super().__init__(
            "The organisation was not set. Either set it using GrabCadAPI.add_default_organisation() call"
            "or pass explicitly to the corresponding method")


class InvalidProjectUrl(Exception):
    def __init__(self, url):
        super().__init__(
            f"Provided url {url} is invalid. Please provide correct url"
            f"of form https://workbench.grabcad.com/workbench/projects/<project_id>#/home")


class RepoNotInitialized(Exception):
    def __init__(self):
        super().__init__("Please initialize repo with `pygc.py init` before using commands")
