import typer
from pathlib import Path
import httpx
import json
import subprocess
import dotenv
import os
import glob
import ssl
import platform
import tarfile
import zipfile
import shutil
from utils import dmgextractor

app = typer.Typer()
# Load the environment variables
dotenv.load_dotenv()
github_token = os.getenv("GITHUB_TOKEN")
if not github_token:
    raise ValueError("GitHub token not found in environment variables.")

def download_blender(tag: str = typer.Option(None, help="Specific Blender tag to download")):
    
    tag = tag.lstrip('v');
    parts = tag.split('.')
    major_version = '.'.join(parts[:2])
    minor_version = '.'.join(parts[:3])
    
    # Determine the OS type (Linux, Windows, MacOS)
    os_type = platform.system()
    arch = platform.machine()
    filename = ""

    # Construct the download URL based on the OS type and Blender version
    if os_type == "Linux":
        filename = f"blender-{minor_version}-linux-x64.tar.xz"
        url = f"https://mirrors.ocf.berkeley.edu/blender/release/Blender{major_version}/{filename}"
        file_ext = "tar.xz"
    elif os_type == "Windows":
        filename = f"blender-{minor_version}-windows-x64.zip"
        url = f"https://mirrors.ocf.berkeley.edu/blender/release/Blender{major_version}/{filename}"
        file_ext = "zip"
    elif os_type == "Darwin":  # MacOS
        macos_arch = "arm64" if arch == "arm64" else "x64"
        filename = f"blender-{minor_version}-macos-{macos_arch}.dmg"
        url = f"https://mirrors.ocf.berkeley.edu/blender/release/Blender{major_version}/{filename}"
        file_ext = "dmg"
    else:
        raise Exception("Unsupported operating system")
    
    download_dir = Path.cwd() / "../downloads"
    download_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Downloading Blender from {url}")
    # Download the file
    with httpx.Client() as client:
        response = client.get(url)
        if response.status_code == 200:
            with open(download_dir / filename, 'wb') as file:
                file.write(response.content)
        else:
            raise Exception(f"Failed to download Blender. Status code: {response.status_code}")

    print(f"Downloaded Blender to {download_dir / filename}")

    bin_dir = Path.cwd() / "../blender-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    # empty the bin directory
    for file in bin_dir.glob("*"):
        if file.is_file():
            file.unlink()
        else:
            shutil.rmtree(file)
    # Extract the file
    if file_ext == "tar.xz":
        with tarfile.open(download_dir / filename, "r:xz") as tar:
            tar.extractall(bin)
    elif file_ext == "zip":
        with zipfile.ZipFile(download_dir / filename, 'r') as zip_ref:
            zip_ref.extractall(bin_dir)
    elif file_ext == "dmg":
        with dmgextractor.DMGExtractor(download_dir / filename) as extractor:
            extractor.extractall(bin_dir)
    print(f"Extracted Blender to {bin_dir}")


@app.command()
def publish_github(tag: str, wheel_dir: Path):
    """ Publishes the wheel file to GitHub Releases. """
    headers = {
    "Authorization": f"Bearer {github_token}",
    "Accept": "application/vnd.github.v3+json"
    }
    ssl_context = ssl.create_default_context()


    client = httpx.Client(headers=headers, verify=ssl_context)
    whl_files = list(wheel_dir.glob("*.whl"))
    if not whl_files:
        raise FileNotFoundError("No .whl file found in the specified directory.")
    whl_file_path = whl_files[0]
           
    print(f"Wheel file found: {whl_file_path}")
    selected_tag = tag  
    # https://docs.github.com/en/rest/reference/repos#create-a-release

    # check if the release already exists
    release_url = f"https://api.github.com/repos/michaelgold/bpy/releases/tags/{selected_tag}"
    # response = requests.get(release_url, headers=headers)

    try:
        # response = requests.get(release_url, headers=headers)
        response = client.get(release_url)
        print(f"GET request to {release_url} completed with status code: {response.status_code}")
        print(f"Response JSON: {response.json()}")
    except httpx.RequestError as e:
        raise Exception(f"Error during GET request to {release_url}: {e}")

    print(f"response code: {response.status_code}")
    print(f"response json: {response.json()}")

    if response.status_code == 200 or response.status_code == 201:
        print("Release already exists. Skipping creation.")
    
        response_json = response.json()
        release_id = response_json.get("id", None)
        print(f"Release ID: {release_id}")

        release_assets = response_json.get("assets", [])
        existing_asset = None
        for asset in release_assets:
            if asset["name"] == f"{whl_file_path.stem}.whl":
                existing_asset = asset
                break
        
        if existing_asset:
            # Delete the existing asset
            print("Deleting existing asset.")
            asset_id = existing_asset["id"]
            delete_url = f"https://api.github.com/repos/michaelgold/bpy/releases/assets/{asset_id}"
            response = client.delete(delete_url)
            print(f"Asset deleted response code: {response.status_code}")
        
    else:
        print("Creating release.")
        # Step 1: Create the release

        release_name = f"gold-bpy-{selected_tag}"
        release_body = f"Blender Python API for Blender {selected_tag}"
        release_tag = f"gold-bpy-{selected_tag}"
        release_url = f"https://api.github.com/repos/michaelgold/bpy/releases"
        release_data = {
            "tag_name": selected_tag,
            "target_commitish": "main",
            "name": release_name,
            "body": release_body,
            "draft": False,
            "prerelease": False
        }
        response = client.post(release_url, json=release_data)


        if response.status_code != 200 and response.status_code != 201:
            raise Exception(f"Failed to get release info: {response.text}")

        release_id = response.json()['id']

    # Step 2: Upload the .whl file
    upload_url = f"https://uploads.github.com/repos/michaelgold/bpy/releases/{release_id}/assets?name={whl_file_path.stem}.whl"
    headers['Content-Type'] = 'application/octet-stream'

    print(f"Uploading file to {upload_url}...")

    # with open(whl_file_path, 'rb') as file:
    #     upload_response = requests.post(upload_url, headers=headers, data=file)
    print(f"Attempting to upload file to {upload_url}")
    try:
        with open(whl_file_path, 'rb') as file:
            upload_response = client.post(upload_url, content=file, headers=headers)
            print(f"POST request to {upload_url} completed with status code: {upload_response.status_code}")
            if upload_response.status_code not in [200, 201]:
                print(f"Failed to upload asset: {upload_response.text}")
            else:
                print("File uploaded successfully.")
    except httpx.RequestError as e:
        raise Exception(f"Error during POST request to {upload_url}: {e}")


    # if upload_response.status_code not in [200, 201]:
    #     raise Exception(f"Failed to upload asset: {upload_response.text}")

    # print("File uploaded successfully.")

def check_new_tag(tag: str = None):
    client = httpx.Client()
    repo_url = "https://api.github.com/repos/blender/blender"
    data_file_path: Path = Path.cwd() / "data.json"
    # Get the tags from the GitHub API
    response = client.get(f"{repo_url}/tags")
    tags = response.json()

    # Determine which tag to use
    if tag and any(t['name'] == tag for t in tags):
        selected_tag = tag
    elif not tag:
        selected_tag = tags[0]['name']
    else:
        print(f"Tag '{tag}' not found.")
        return False

    # Load the current tag from the data file
    if data_file_path.exists():
        with open(data_file_path, 'r') as file:
            tag_data = json.load(file)
            current_tag = tag_data.get("latest_tag", "")
    else:
        current_tag = ""
        tag_data = {}
    
    if (selected_tag == current_tag) and (tag is None):
        # If the tag is the same as the current tag, and no specific tag was provided, do nothing
        print(f"Tag '{selected_tag}' is already checked out.")
        return False

    else:
        # If the tag is different from the current tag, or a specific tag was provided, update the local repository and build blender
        print(f"Tag found: {selected_tag}. Updating and checking out the repo.")

        # Clone the repository and checkout the selected tag
        # subprocess.run(["git", "clone", "https://github.com/blender/blender.git"])
        blender_repo_dir = Path.cwd() / "../blender"
        subprocess.run(["git", "fetch", "--all"], cwd=blender_repo_dir)
        subprocess.run(["git", "checkout", f"tags/{selected_tag}"], cwd=blender_repo_dir)

        # Build blender
        subprocess.run(["make", "update"], cwd=blender_repo_dir)
        # subprocess.run(["make", "bpy"], cwd=blender_repo_dir)

        # tag_parts = selected_tag.split('.')
        # major_version = '.'.join(tag_parts[:2])
        # minor_version = '.'.join(tag_parts[:3])

        #./blender --background --factory-startup -noaudio --python ../blender-git/doc/python_api/sphinx_doc_gen.py -- --output=../python_api
        python_api_dir = Path.cwd() / "../python_api"

        download_blender(selected_tag)

        blender_binary = Path.cwd() / "../blender-bin/Blender.app/Contents/MacOS/Blender"

        # build the python api docs
        subprocess.run([blender_binary, "--background", "--factory-startup", "-noaudio", "--python", blender_repo_dir / "doc/python_api/sphinx_doc_gen.py", "--", f"--output={python_api_dir}"])
        build_dir = Path.cwd() / "../build_darwin_bpy"

        # build the python api stubs in the build directory (for the wheel)
        subprocess.run(["python", "-m", "bpystubgen", python_api_dir / "sphinx-in", build_dir / "bin"])



        # Make the wheel

       

        subprocess.run(["pip", "install", "-U", "pip", "setuptools", "wheel"])
        make_script = Path.cwd() / "../blender/build_files/utils/make_bpy_wheel.py"

        shutil.copy2(Path.cwd() / "make_bpy_wheel.py", make_script )
        subprocess.run(["python", make_script, build_dir / "bin/"])

        # Get the wheel file
        bin_path = build_dir / "bin"



        publish_github(selected_tag, bin_path)
        




        # Update the data file
        tag_data["latest_tag"] = selected_tag
        with open(data_file_path, 'w') as file:
            json.dump(tag_data, file)
        
        return True
   
@app.command()
def build(tag: str = typer.Option(None, help="Specific tag to check out")):
    """
    This script checks for new tags in the Blender repository on GitHub.
    If a new tag is found, or a specific tag is provided, it updates the local repository and a data file.
    """
    os.chdir(Path(__file__).parent)
    check_new_tag(tag)

if __name__ == "__main__":
    app()
