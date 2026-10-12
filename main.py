import os
import subprocess
import sys


def check_rscript():
    try:
        subprocess.run(["Rscript", "--version"], check=True, capture_output=True)
    except FileNotFoundError:
        print("Rscript is not installed. Please install R before launching SiGMaR.")
        sys.exit(1)


if __name__ == "__main__":
    check_rscript()

    from app import app

    port = int(os.environ.get("PORT", "8060"))
    app.run(debug=False, port=port, host="0.0.0.0")
