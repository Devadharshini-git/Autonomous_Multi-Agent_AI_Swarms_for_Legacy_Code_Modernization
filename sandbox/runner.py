# sandbox/runner.py
"""
Docker Sandbox Runner — Part 5
Builds a Docker image for a generated service and runs its tests
inside an isolated container. Captures pass/fail results as JSON.
"""

import docker
import json
import os
import shutil


def run_tests_in_sandbox(service_name: str) -> dict:
    """
    Builds a Docker image from the generated service folder and runs
    pytest inside a container. Returns structured results.
    """
    service_dir = os.path.abspath(os.path.join("generated", service_name))
    dockerfile_src = os.path.abspath(os.path.join("sandbox", "Dockerfile"))

    dockerfile_dest = os.path.join(service_dir, "Dockerfile")
    shutil.copy(dockerfile_src, dockerfile_dest)

    client = docker.from_env()
    image_tag = f"{service_name}-sandbox:latest"

    result = {
        "service_name": service_name,
        "build_success": False,
        "tests_passed": False,
        "output": "",
        "error": None,
    }

    try:
        print(f"🔨 Building Docker image: {image_tag} ...")
        image, build_logs = client.images.build(
            path=service_dir,
            tag=image_tag,
            rm=True,
        )
        result["build_success"] = True
        print("✅ Image built successfully.")

        print("🏃 Running tests in container...")
        container = client.containers.run(
            image_tag,
            detach=True,
        )
        exit_code = container.wait()
        logs = container.logs().decode("utf-8")
        result["output"] = logs
        result["tests_passed"] = exit_code["StatusCode"] == 0

        container.remove()

        if result["tests_passed"]:
            print("✅ All tests passed inside the sandbox.")
        else:
            print("❌ Some tests failed. See output below.")
            print(logs)

    except docker.errors.BuildError as e:
        result["error"] = f"Build failed: {str(e)}"
        print("❌ Docker build failed:", e)

    except Exception as e:
        result["error"] = str(e)
        print("❌ Unexpected error:", e)

    finally:
        if os.path.exists(dockerfile_dest):
            os.remove(dockerfile_dest)

    return result


if __name__ == "__main__":
    SERVICE_NAME = "inventory_service"
    result = run_tests_in_sandbox(SERVICE_NAME)
    print("\n--- Structured Result ---")
    print(json.dumps({k: v for k, v in result.items() if k != "output"}, indent=2))