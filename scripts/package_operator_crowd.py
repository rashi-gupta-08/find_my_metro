"""Package verified evidence and code fingerprints, excluding private runtime data."""
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import shutil
import zipfile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/operator-crowd-100-users'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert json.loads((OUT/'verification.json').read_text())['all_checks_passed']
    assert json.loads((OUT/'panel-viewer-verification.json').read_text())['all_checks_passed']
    assert (OUT/'FindMyMetro_Combined_Test_Results.pdf').exists()
    # Remove only duplicate script copies created by the first report draft.
    for name in ['audit_operator_baseline.py','test_operator_crowd_100.py','verify_operator_crowd.py',
                 'plot_operator_crowd.py','write_operator_crowd_report.py']:
        duplicate=OUT/'reproduction'/name
        if duplicate.is_file():duplicate.unlink()
    # Preserve the actual source paths, never .env, databases, logs or sessions.
    code=sorted((ROOT/'backend/app').glob('*.py'))+sorted((ROOT/'backend/migrations').rglob('*.py'))
    code += [ROOT/'alembic.ini', ROOT/'backend/requirements.lock.txt']
    code += [ROOT/'scripts'/name for name in ['audit_operator_baseline.py','test_operator_crowd_100.py',
        'verify_operator_crowd.py','plot_operator_crowd.py','write_operator_crowd_report.py',
        'check_operator_crowd_panel.cjs','package_operator_crowd.py','operator_crowd_delay_view.py']]
    fingerprints=[]
    for source in code:
        relative=source.relative_to(ROOT)
        target=OUT/'reproduction'/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,target)
        fingerprints.append({'project_path':relative.as_posix(),'sha256':sha(source)})
    (OUT/'source-code-fingerprints.json').write_text(json.dumps(fingerprints,indent=2)+'\n')
    dependencies={name:version(name) for name in ['fastapi','starlette','uvicorn','SQLAlchemy','alembic','pydantic','psycopg','httpx','websockets','networkx']}
    (OUT/'runtime-packages.json').write_text(json.dumps(dependencies,indent=2)+'\n')
    (OUT/'reproduction/README.md').write_text('''# Captured implementation source

The backend and runner files are captured at their project-relative paths. Use the complete local FindMyMetro project to rerun the experiment, following the main README. This folder records code for audit; it does not ship private PostgreSQL credentials, the .env file, source installation archives, or virtual environments. Public cached operator responses are in ../operator-source-responses. Account and session provisioning occurs afresh inside a disposable test database.

The plotting script requires matplotlib/numpy; document generation requires python-docx and Word or an available DOCX renderer. Figures and reports are already generated, so these authoring tools are not required to view the results.
''',encoding='utf-8')
    archive=OUT/'FindMyMetro_Operator_Crowd_100_User_Evidence.zip'
    files=sorted(p for p in OUT.rglob('*') if p.is_file() and p!=archive and p.name!='evidence-manifest.json')
    prohibited={'.env','test.env','pg-password.txt','database.json','processes.json'}
    assert not any(p.name in prohibited or p.suffix in {'.db','.sqlite','.log'} for p in files)
    manifest={'scope':'Operator snapshot plus synthetic crowd test and actual software measurements; no field arrival ground truth.',
        'files':[{'path':p.relative_to(OUT).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)} for p in files]}
    (OUT/'evidence-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    files.append(OUT/'evidence-manifest.json')
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=7) as pack:
        for p in files:pack.write(p,p.relative_to(OUT).as_posix())
    with zipfile.ZipFile(archive) as pack:
        assert pack.testzip() is None
        for item in manifest['files']:
            assert hashlib.sha256(pack.read(item['path'])).hexdigest()==item['sha256']
    print(json.dumps({'archive':str(archive),'files':len(files),'bytes':archive.stat().st_size,
        'all_member_hashes_verified':True,'private_runtime_files_excluded':True},indent=2))


if __name__=='__main__':main()
