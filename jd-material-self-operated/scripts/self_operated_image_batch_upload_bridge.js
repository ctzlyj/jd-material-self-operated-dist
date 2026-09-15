(async () => {
  const action = __JD_SELF_OPERATED_UPLOAD_BATCH_ACTION__;
  const execute = (singleAction) => __JD_SELF_OPERATED_UPLOAD_SINGLE_SOURCE__;
  const files = action.files || [];
  const concurrency = action.concurrency ?? 1;
  if (!action.expectedErp || !files.length || !Number.isInteger(concurrency) || concurrency < 1) {
    throw new Error("batch upload requires an ERP, files and positive concurrency");
  }
  const results = files.map(item => ({ fileName: item.fileName, status: "not-submitted" }));
  try {
    const prefixes = files.map(item => String(item.fileName || "").match(/^\d+/)?.[0]);
    if (prefixes.some(prefix => !prefix) ||
        new Set(files.map(item => item.fileName)).size !== files.length) {
      throw new Error("batch upload requires unique authorized product filenames");
    }
    const staged = Array.from(document.getElementById(action.fileInputId)?.files || []);
    if (staged.length !== files.length) throw new Error("staged file count differs from the plan");
    for (const item of files) {
      const matches = staged.filter(file => file.name === item.fileName);
      if (matches.length !== 1 || !/^[a-f0-9]{64}$/.test(item.expectedSha256 || "")) {
        throw new Error("staged file identity is invalid");
      }
      const digest = await crypto.subtle.digest("SHA-256", await matches[0].arrayBuffer());
      const actual = Array.from(new Uint8Array(digest)).map(value => value.toString(16).padStart(2, "0")).join("");
      if (actual !== item.expectedSha256) throw new Error("staged file hash differs from the plan");
    }
  } catch (_error) {
    return results.map(item => ({ ...item, code: "STAGED_FILES_INVALID" }));
  }
  let next = 0;
  let stopped = false;
  const worker = async () => {
    while (!stopped && next < files.length) {
      const index = next++;
      const item = files[index];
      try {
        await execute({ kind: "verifyIdentity", expectedErp: action.expectedErp });
      } catch (_error) {
        results[index].code = "ERP_VERIFICATION_FAILED";
        stopped = true;
        break;
      }
      if (stopped) break;
      try {
        const response = await execute({
          ...item, kind: "uploadImage", fileInputId: action.fileInputId,
          categoryId: action.categoryId, shouldStop: () => stopped,
        });
        if (!response || response.name !== item.fileName) throw new Error("upload response filename differs from the plan");
        results[index] = { fileName: item.fileName, status: "submitted", response };
      } catch (_error) {
        results[index] = { fileName: item.fileName, status: "unconfirmed", code: "UPLOAD_OUTCOME_UNCONFIRMED" };
        stopped = true;
        break;
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(concurrency, files.length) }, worker));
  return results;
})()
