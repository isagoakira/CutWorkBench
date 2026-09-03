class WorkbenchError(Exception):
    """Base error for user-visible workbench failures."""


class ValidationError(WorkbenchError):
    """A request violates a project or protocol invariant."""


class RevisionConflict(WorkbenchError):
    """The caller attempted to mutate a stale project revision."""


class ProjectNotFound(WorkbenchError):
    """The requested project or revision does not exist."""
