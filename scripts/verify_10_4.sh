#!/bin/bash
set -e

echo "Starting Phase 10.4 Verification..."

# Cleanup
echo "Cleaning up..."
rm -rf projects/exec_local_ok projects/exec_sub_ok projects/q_exec_1 projects/q_exec_2

# Ensure PYTHONPATH is set
export PYTHONPATH=.

# Test A — LocalExecutor parity
echo "Running Test A: LocalExecutor parity..."
python3 -m dawn.runtime.new --project exec_local_ok --pipeline-id test_10_3_success --profile normal
echo "test idea" > projects/exec_local_ok/inputs/idea.md
python3 -m dawn.runtime.pipelines run --id test_10_3_success --project exec_local_ok --executor local

if [ -f projects/exec_local_ok/artifacts/package.project_report/project_report.html ]; then
    echo "✅ Test A Passed: Project report generated via LocalExecutor."
else
    echo "❌ Test A Failed: Project report NOT generated."
    exit 1
fi

# Test B — SubprocessExecutor works
echo "Running Test B: SubprocessExecutor works..."
python3 -m dawn.runtime.new --project exec_sub_ok --pipeline-id test_10_3_success --profile isolation
echo "test" > projects/exec_sub_ok/inputs/idea.md
python3 -m dawn.runtime.pipelines run --id test_10_3_success --project exec_sub_ok --executor subprocess

if [ -f projects/exec_sub_ok/ledger/worker.log ]; then
    echo "✅ Test B.1 Passed: worker.log created."
else
    echo "❌ Test B.1 Failed: worker.log NOT created."
    exit 1
fi

if [ -f projects/exec_sub_ok/artifacts/package.project_report/project_report.html ]; then
    echo "✅ Test B.2 Passed: Project report generated via SubprocessExecutor."
else
    echo "❌ Test B.2 Failed: Project report NOT generated."
    exit 1
fi

# Test C — Queue uses executor consistently
echo "Running Test C: Queue uses executor consistently..."
python3 -m dawn.runtime.queue clear
python3 -m dawn.runtime.queue submit --project q_exec_1 --pipeline-id test_10_3_success --profile normal --executor local --priority 10
python3 -m dawn.runtime.queue submit --project q_exec_2 --pipeline-id test_10_3_success --profile normal --executor subprocess --priority 5

echo "Starting queue..."
python3 -m dawn.runtime.queue run --max 2
python3 -m dawn.runtime.queue status

if python3 -m dawn.runtime.queue status | grep -q "COMPLETED"; then
    echo "✅ Test C Passed: Queue completed projects."
else
    echo "❌ Test C Failed: Queue did not complete any project."
    exit 1
fi

echo "Phase 10.4 Verification Completed Successfully!"
