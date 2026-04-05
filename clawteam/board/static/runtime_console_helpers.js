(function (global) {
  function makeSelection(type, id, data) {
    return { type, id, data };
  }

  function buildSelectionMap(runtime) {
    const map = new Map();
    const workers = runtime.workers || [];
    const tasks = runtime.tasks || [];
    const jobs = runtime.jobs || [];
    const sessions = runtime.sessions || [];
    const faults = runtime.faults || [];
    const timeline = runtime.timeline || [];

    workers.forEach((worker) => map.set(`worker:${worker.name}`, makeSelection("worker", worker.name, worker)));
    tasks.forEach((task) => map.set(`task:${task.id}`, makeSelection("task", task.id, task)));
    jobs.forEach((job) => map.set(`job:${job.jobId}`, makeSelection("job", job.jobId, job)));
    sessions.forEach((session) => map.set(`session:${session.sessionId}`, makeSelection("session", session.sessionId, session)));
    faults.forEach((fault) => {
      const id = fault.faultId || fault.message;
      map.set(`fault:${id}`, makeSelection("fault", id, fault));
    });
    timeline.forEach((event) => map.set(`event:${event.eventId}`, makeSelection("event", event.eventId, event)));
    return map;
  }

  function selectDefaultRuntimeObject(runtime) {
    if (runtime.faults && runtime.faults.length) {
      const fault = runtime.faults[0];
      return makeSelection("fault", fault.faultId || fault.message, fault);
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

  const api = {
    artifactPreviewRoute,
    resolveSelection,
    selectDefaultRuntimeObject,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }

  global.RuntimeConsoleHelpers = api;
})(typeof window !== "undefined" ? window : globalThis);
