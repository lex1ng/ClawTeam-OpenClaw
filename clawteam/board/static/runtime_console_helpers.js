(function (global) {
  function makeSelection(type, id, data) {
    return { type, id, data };
  }

  function callbackSelectionId(callback) {
    if (callback.callbackId) return callback.callbackId;
    if (callback.callbackLevel === "team") {
      return `team:${callback.reportedAt || "latest"}`;
    }
    return `${callback.jobId || "unknown"}:${callback.reportedAt || "latest"}`;
  }

  function buildSelectionMap(runtime) {
    const map = new Map();
    const workers = runtime.workers || [];
    const tasks = runtime.tasks || [];
    const jobs = runtime.jobs || [];
    const sessions = runtime.sessions || [];
    const faults = runtime.faults || [];
    const callbacks = runtime.callbacks || [];
    const timeline = runtime.timeline || [];
    const evidence = runtime.evidence?.records || [];
    const chainWorkers = runtime.callbackChain?.workers || [];
    const teamChain = runtime.callbackChain?.team;

    workers.forEach((worker) => map.set(`worker:${worker.name}`, makeSelection("worker", worker.name, worker)));
    tasks.forEach((task) => map.set(`task:${task.id}`, makeSelection("task", task.id, task)));
    jobs.forEach((job) => map.set(`job:${job.jobId}`, makeSelection("job", job.jobId, job)));
    sessions.forEach((session) => map.set(`session:${session.sessionId}`, makeSelection("session", session.sessionId, session)));
    faults.forEach((fault) => {
      const id = fault.faultId || fault.message;
      map.set(`fault:${id}`, makeSelection("fault", id, fault));
    });
    callbacks.forEach((callback) => {
      const id = callbackSelectionId(callback);
      map.set(`callback:${id}`, makeSelection("callback", id, callback));
    });
    chainWorkers.forEach((row) => {
      const id = `chain-worker:${row.workerName}`;
      map.set(`callback:${id}`, makeSelection("callback", id, row));
    });
    if (teamChain) {
      map.set("callback:chain-team", makeSelection("callback", "chain-team", teamChain));
    }
    evidence.forEach((item) => {
      const id = item.evidenceId || `${item.sourceType || "evidence"}:${item.sourceId || "unknown"}`;
      map.set(`evidence:${id}`, makeSelection("evidence", id, item));
    });
    timeline.forEach((event) => map.set(`event:${event.eventId}`, makeSelection("event", event.eventId, event)));
    return map;
  }

  function selectDefaultRuntimeObject(runtime) {
    if (runtime.faults && runtime.faults.length) {
      const fault = runtime.faults[0];
      return makeSelection("fault", fault.faultId || fault.message, fault);
    }
    if (runtime.callbackChain && runtime.callbackChain.workers && runtime.callbackChain.workers.length) {
      const row = runtime.callbackChain.workers.find((item) => item.callbackState !== "reported") || runtime.callbackChain.workers[0];
      return makeSelection("callback", `chain-worker:${row.workerName}`, row);
    }
    if (runtime.evidence && runtime.evidence.records && runtime.evidence.records.length) {
      const item = runtime.evidence.records[0];
      return makeSelection("evidence", item.evidenceId || "evidence", item);
    }
    if (runtime.sessions && runtime.sessions.length) {
      return makeSelection("session", runtime.sessions[0].sessionId, runtime.sessions[0]);
    }
    if (runtime.jobs && runtime.jobs.length) {
      return makeSelection("job", runtime.jobs[0].jobId, runtime.jobs[0]);
    }
    if (runtime.tasks && runtime.tasks.length) {
      return makeSelection("task", runtime.tasks[0].id, runtime.tasks[0]);
    }
    return null;
  }

  function resolveSelection(previousSelection, runtime) {
    if (!runtime) return null;
    if (!previousSelection) {
      return selectDefaultRuntimeObject(runtime);
    }
    const selectionMap = buildSelectionMap(runtime);
    return selectionMap.get(`${previousSelection.type}:${previousSelection.id}`) || selectDefaultRuntimeObject(runtime);
  }

  function artifactPreviewRoute(teamName, jobId, artifactName) {
    return `/api/teams/${encodeURIComponent(teamName)}/coding/jobs/${encodeURIComponent(jobId)}/artifacts/${encodeURIComponent(artifactName)}`;
  }

  function evidenceDetailRoute(teamName, evidenceId) {
    return `/api/teams/${encodeURIComponent(teamName)}/evidence/${encodeURIComponent(evidenceId)}`;
  }

  const api = {
    artifactPreviewRoute,
    evidenceDetailRoute,
    resolveSelection,
    selectDefaultRuntimeObject,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }

  global.RuntimeConsoleHelpers = api;
})(typeof window !== "undefined" ? window : globalThis);
