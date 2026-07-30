# KB AI Data Pipeline

AIHub 데이터의 등록·무결성·개인정보 가능 패턴·평가 준비 상태를 관리하는 별도
Airflow 저장소입니다. FastAPI의 실시간 요청 경로와 분리하며 금융 실행 권한이나
`core` 스키마 수정 권한을 갖지 않습니다.

현재 MVP는 `aiserver/sample/aihub*` 경량 샘플만 읽습니다. 전체 데이터셋을
승인된 Object Storage 또는 별도 로컬 볼륨으로 옮긴 뒤에도 동일한 DAG를 사용할 수
있도록 입력 루트와 실행 모드를 환경변수로 분리했습니다.

## 로컬 실행

요구사항:

- Docker Desktop
- Docker Compose v2
- Docker에 최소 4GB, 권장 8GB 메모리
- `../aiserver/sample` 아래의 AIHub 경량 샘플

```bash
cp .env.example .env
docker compose up airflow-init
docker compose up -d
docker compose ps
```

Airflow UI는 <http://localhost:18080>에서 열립니다. 로컬 기본 계정은
`.env.example`의 `airflow`/`airflow`이며 비로컬 환경에서는 반드시 교체합니다.

수동 실행:

```bash
docker compose exec airflow-scheduler \
  airflow dags trigger aihub_dataset_governance
```

중지:

```bash
docker compose down
```

볼륨까지 삭제하는 `docker compose down --volumes`는 로컬 Airflow 메타데이터를
모두 삭제하므로 의도한 경우에만 사용합니다.

## DAG 책임

`aihub_dataset_governance`는 다음 순서로 실행됩니다.

1. `config/datasets.json`의 허용 데이터셋만 찾습니다.
2. 파일 수·크기·확장자·경로와 내용의 집계 SHA-256을 계산합니다.
3. 텍스트 파일에서 개인정보 가능 패턴의 개수만 집계합니다.
4. 원문 없이 데이터셋별 감사 JSON과 실행 요약 JSON을 `artifacts/`에 기록합니다.

압축파일 내부와 이미지 개인정보 검사는 완료된 것으로 간주하지 않고 반드시
`REVIEW_REQUIRED`로 남깁니다. 원문, 번역문, OCR 라벨 값, 이미지, 식별번호는
Airflow XCom·로그·PostgreSQL에 기록하지 않습니다.

## 전체 AIHub 데이터 확장

전체 데이터 사용 권한과 재사용 조건을 데이터셋별로 다시 확인한 후 `.env`에서
입력만 전환합니다.

```dotenv
AIHUB_DATA_MODE=FULL
AIHUB_DATASET_ROOT=/absolute/path/to/approved/aihub
```

전체 데이터는 저장소에 커밋하지 않습니다. 운영에서는 로컬 bind mount 대신
암호화된 S3 호환 Object Storage를 사용하고 Airflow에는 객체 경로·버전·체크섬만
전달합니다. 단일 작업 처리시간이나 메모리가 목표를 넘을 때만 Spark 작업을 DAG
하위 단계로 추가합니다. Kafka와 Flink는 실시간 스트림 요구가 생기기 전까지
도입하지 않습니다.

## 검증

Airflow를 설치하지 않아도 핵심 감사 로직을 검증할 수 있습니다.

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall dags src tests
docker compose config --quiet
```

Airflow 컨테이너가 실행 중이면 DAG import도 확인합니다.

```bash
docker compose exec airflow-scheduler airflow dags list-import-errors
docker compose exec airflow-scheduler airflow dags test \
  aihub_dataset_governance 2026-07-30
```
