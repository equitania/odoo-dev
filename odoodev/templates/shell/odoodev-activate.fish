# odoodev shell integration for Fish
# Install: odoodev shell-setup
function odoodev-activate
    set -l version $argv[1]
    if test -z "$version"
        echo "Usage: odoodev-activate <version>" >&2
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
