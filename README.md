## Installation

The project uses a `pyproject.toml` based install. It is recommended to install in "editable" mode so that the `lib` modules are correctly resolved in the Python path and the command is globally accessible.

1.  **Clone the repository:**
    ```bash
    git clone [https://github.com/joospis/topo_around_buffer.git](https://github.com/joospis/topo_around_buffer.git)
    cd topo_around_buffer
    ```

2.  **Install in editable mode:**
    ```bash
    pip install -e .
    ```

---

## Usage

The installation creates a global command `tiles-from-ref`.

```bash
usage: tiles-from-ref [-h] [--trail_id TRAIL_ID] [--buffer_radius BUFFER_RADIUS] 
                      reference_geometry output_dir
```

