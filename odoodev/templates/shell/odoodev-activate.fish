# odoodev shell integration for Fish
# Install: odoodev shell-setup
function __odoodev_check_health
    # Verify the odoodev interpreter is functional before calling it.
    # UV tool environments break when Python versions are removed/updated.
    set -l odoodev_bin (command -s odoodev 2>/dev/null)
    if test -z "$odoodev_bin"
        echo "odoodev not found in PATH. Install: uv tool install odoodev-equitania" >&2
        return 1
    end

    # Resolve symlinks to find the actual script
    set -l real_bin (realpath "$odoodev_bin" 2>/dev/null; or echo "$odoodev_bin")

    # Read shebang interpreter from the script
    set -l shebang (head -1 "$real_bin" 2>/dev/null)
    if string match -q '#!*' "$shebang"
        set -l interpreter (string replace '#!' '' "$shebang" | string trim)
        # Follow symlink chain to final target
        set -l target (realpath "$interpreter" 2>/dev/null)
        if test $status -ne 0; or not test -x "$target"
            echo "" >&2
            echo "[ERROR] odoodev interpreter broken: $interpreter" >&2
            echo "  The Python installation used by odoodev was removed or updated." >&2
            echo "  Fix: uv tool upgrade --all" >&2
            echo "" >&2
            return 1
        end
    end
    return 0
end

function odoodev-activate
    set -l version $argv[1]
    if test -z "$version"
        echo "Usage: odoodev-activate <version>" >&2
        return 1
    end

    # Pre-flight: check odoodev interpreter health
    if not __odoodev_check_health
        return 1
    end

    set -l venv_dir (odoodev venv path $version)
    set -l env_dir (odoodev env dir $version)
    if test -d "$venv_dir"
        source "$venv_dir/bin/activate.fish"
        cd "$env_dir"
        echo "Activated Odoo v$version environment"
    else
        echo "No venv found for v$version. Run: odoodev venv setup $version" >&2
        return 1
    end
end
