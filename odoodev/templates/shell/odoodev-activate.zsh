# odoodev shell integration for Zsh
# Install: odoodev shell-setup
odoodev-activate() {
    local version="$1"
    if [ -z "$version" ]; then
        echo "Usage: odoodev-activate <version>" >&2
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
