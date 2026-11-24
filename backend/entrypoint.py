import os
import pwd
import sys
from pathlib import Path


def main() -> None:
    app_user = pwd.getpwnam("appuser")
    data_dir = Path("/data")

    # Persistent-volume mounts can replace the image directory and its ownership.
    # Fix the mount and existing SQLite files before dropping privileges.
    if os.geteuid() == 0:
        for current, directories, files in os.walk(data_dir):
            os.chown(current, app_user.pw_uid, app_user.pw_gid)
            for name in (*directories, *files):
                os.chown(Path(current) / name, app_user.pw_uid, app_user.pw_gid)
        os.setgroups([])
        os.setgid(app_user.pw_gid)
        os.setuid(app_user.pw_uid)

    if len(sys.argv) < 2:
        raise SystemExit("entrypoint requires a command")
    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()
