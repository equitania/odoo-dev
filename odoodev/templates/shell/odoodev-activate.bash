# odoodev shell integration for Bash
# Install: odoodev shell-setup
__odoodev_check_health() {
    # Verify the odoodev interpreter is functional before calling it.
    # UV tool environments break when Python versions are removed/updated.
    local odoodev_bin
    odoodev_bin=$(command -v odoodev 2>/dev/null)
    if [ -z "$odoodev_bin" ]; then
        echo "odoodev not found in PATH. Install: uv tool install odoodev-equitania" >&2
        return 1
    fi

    # Resolve symlinks to find the actual script
    local real_bin
    real_bin=$(realpath "$odoodev_bin" 2>/dev/null || echo "$odoodev_bin")

    # Read shebang interpreter from the script
    local shebang
    shebang=$(head -1 "$real_bin" 2>/dev/null)
    if [[ "$shebang" == "#!"* ]]; then
        local interpreter="${shebang#\#!}"
        interpreter=$(echo "$interpreter" | xargs)  # trim whitespace
        # Follow symlink chain to final target
        local target
        target=$(realpath "$interpreter" 2>/dev/null)
        if [ $? -ne 0 ] || [ ! -x "$target" ]; then
            echo "" >&2
            echo "[ERROR] odoodev interpreter broken: $interpreter" >&2
            echo "  The Python installation used by odoodev was removed or updated." >&2
            echo "  Fix: uv tool upgrade --all" >&2
            echo "" >&2
            return 1
        fi
    fi
    return 0
}

odoodev-activate() {
    local version="$1"
    if [ -z "$version" ]; then
        echo "Usage: odoodev-activate <version>" >&2
        return 1
    fi

    # Pre-flight: check odoodev interpreter health
    if ! __odoodev_check_health; then
        return 1
    fi

    local venv_dir
    venv_dir=$(odoodev venv path "$version")
    local env_dir
    env_dir=$(odoodev env dir "$version")
    if [ -d "$venv_dir" ]; then
        source "$venv_dir/bin/activate"
        cd "$env_dir" || return
        echo "Activated Odoo v$version environment"
    else
        echo "No venv found for v$version. Run: odoodev venv setup $version" >&2
        return 1
    fi
}
