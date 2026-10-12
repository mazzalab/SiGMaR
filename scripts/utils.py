import os

def ensure_dirs(base_dir, study_name):
    """
    Create study output directory structure
    """
    study_path = os.path.join(base_dir, study_name)
    os.makedirs(study_path, exist_ok=True)
    return study_path