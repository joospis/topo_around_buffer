import subprocess
import shlex
import glob
import os

dirname = os.path.dirname(__file__)

def gen_vector_tiles(dir):
    input_files = glob.glob(os.path.join(dir, "*.fgb"))

    if not input_files:
        print(f"Error: No files found matching '*.fgb' in the directory: {dir}")
        return

    input_files_string = " ".join([shlex.quote(f) for f in input_files])
    
    command = f'tippecanoe -o {dir}/../no_world_output.pmtiles -z14 -f {input_files_string} --drop-densest-as-needed --simplification=5 --detect-shared-borders --read-parallel'

    args = shlex.split(command)

    print(f"Executing command: {' '.join(args)}")
    
    try:
        result = subprocess.run(
            args,
            check=True,
            text=True  
        )

        print("\n🎉 Tippecanoe ran successfully.")
        if result.stdout:
            print("Standard Output:\n", result.stdout)
        if result.stderr:
            print("Standard Error (often for progress/warnings):\n", result.stderr)

    except subprocess.CalledProcessError as e:
        print(f"\n❌ Tippecanoe failed with exit code {e.returncode}")
        print("Error Output:\n", e.stderr)
    except FileNotFoundError:
        print("\n⚠️ Error: tippecanoe command not found. Make sure it is installed and in your system PATH.")

if __name__ == "__main__":
    gen_vector_tiles("./out/layers")
    # merge_with_earth("./out/")