"""Open one validated deployment's durable state, immutable objects and fixed lease."""
from pathlib import Path

from ..config import Settings
from .contracts import (AlreadyExists, ClockUncertain, Conflict, LeaseHandle, LeaseStore,
                        ObjectStore, OwnershipLost, StateStore, StoreMissing, BoundaryObserver, deployment_binding)


def open_stores(settings: Settings, *, base_path: Path | None = None, observer: BoundaryObserver | None = None,
                access: str = 'worker', credential=None) -> tuple[StateStore, ObjectStore, LeaseStore | None]:
    """Worker access creates and binds the store; operator access verifies an existing one and takes no lease."""
    if access not in ('worker', 'operator'):
        raise ValueError('store access must be worker or operator')
    validated = Settings.from_mapping(settings.to_mapping())
    if validated.storage.backend == "local-fixture":
        from .local import LocalLeaseStore, LocalObjectStore, LocalStateStore
        root = (base_path if base_path is not None else Path.cwd()) / validated.storage.root
        binding = deployment_binding(validated, root=root)
        if access == 'operator':
            state = LocalStateStore(root, observer=observer, binding=binding, create=False)
            return state, LocalObjectStore(root, observer=observer, binding=binding, create=False), None
        objects = LocalObjectStore(root, observer=observer, binding=binding)
        state = LocalStateStore(root, observer=observer, binding=binding)
        leases = LocalLeaseStore(root, observer=observer, binding=binding)
        return state, objects, leases
    from .azure import open_azure_stores
    return open_azure_stores(validated, observer=observer, access=access, credential=credential)
