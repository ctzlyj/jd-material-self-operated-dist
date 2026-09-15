(async () => {
  const action = __JD_SELF_OPERATED_BINDING_BATCH_ACTION__;
  const execute = (singleAction) => __JD_SELF_OPERATED_BINDING_SINGLE_SOURCE__;
  const requests = action.requests || [];
  const concurrency = action.concurrency ?? 1;
  if (!action.expectedErp || !requests.length || !Number.isInteger(concurrency) || concurrency < 1 ||
      new Set(requests.map(item => item.requestId)).size !== requests.length ||
      new Set(requests.map(item => item.spuId)).size !== requests.length ||
      requests.some(item => !item.requestId || !item.spuId || !["bindImages", "saveSellingPoints"].includes(item.kind))) {
    throw new Error("binding batch requires an ERP, unique products and positive concurrency");
  }
  const results = requests.map(item => ({ requestId: item.requestId, status: "not-submitted", error: "" }));
  let stopped = false;
  let next = 0;
  const worker = async () => {
    while (!stopped && next < requests.length) {
      const index = next++;
      const item = requests[index];
      try {
        const response = await execute({ kind: item.kind, body: item.body, expectedErp: action.expectedErp, shouldStop: () => stopped });
        if (response && response.ok === true) {
          results[index].status = "submitted";
        } else {
          results[index].status = "unconfirmed";
          results[index].error = String(response?.error || response?.errors?.join("；") || "material binding was not accepted").slice(0, 1000);
        }
      } catch (error) {
        results[index].status = "unconfirmed";
        results[index].error = String(error?.message || "material binding outcome is unknown").slice(0, 1000);
        stopped = true;
        break;
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(concurrency, requests.length) }, worker));
  return { results, stopped, concurrent: concurrency > 1 };
})()
