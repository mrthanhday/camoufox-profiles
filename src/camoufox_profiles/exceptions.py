"""Custom exceptions for camoufox-profiles."""


class ProfileNotFoundError(Exception):
    """Raised when a profile cannot be found by ID or name."""

    def __init__(self, identifier: str):
        super().__init__(f"Profile not found: {identifier}")
        self.identifier = identifier


class ProfileNameExistsError(Exception):
    """Raised when attempting to create a profile with a name that already exists."""

    def __init__(self, name: str):
        super().__init__(f"Profile with name '{name}' already exists")
        self.name = name


class ProfileLaunchError(Exception):
    """Raised when a profile fails to launch."""

    def __init__(self, profile_id: str, reason: str):
        super().__init__(f"Failed to launch profile {profile_id}: {reason}")
        self.profile_id = profile_id
        self.reason = reason


class FingerprintCaptureError(Exception):
    """Raised when fingerprint generation or capture fails."""

    def __init__(self, reason: str):
        super().__init__(f"Failed to capture fingerprint: {reason}")
        self.reason = reason


class WarmupError(Exception):
    """Raised when profile warmup fails."""

    def __init__(self, profile_id: str, reason: str):
        super().__init__(f"Warmup failed for profile {profile_id}: {reason}")
        self.profile_id = profile_id
        self.reason = reason
