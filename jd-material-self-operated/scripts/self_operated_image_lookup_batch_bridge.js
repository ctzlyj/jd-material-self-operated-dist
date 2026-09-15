(async () => {
  const action = __JD_SELF_OPERATED_LOOKUP_BATCH_ACTION__;
  const execute = singleAction => __JD_SELF_OPERATED_LOOKUP_SINGLE_SOURCE__;
  const queries = action.queries;
  if (!action.expectedErp || !Array.isArray(queries) || !queries.length || queries.length > 10 ||
      queries.some(query => typeof query !== "string" || !query.trim()) ||
      new Set(queries).size !== queries.length ||
      !Number.isInteger(action.pageSize) || action.pageSize < 1) {
    throw new Error("image lookup requires an ERP, distinct queries and a positive page size");
  }
  await execute({kind: "verifyIdentity", expectedErp: action.expectedErp});
  const results = new Array(queries.length);
  let next = 0;
  let failure = null;
  const worker = async () => {
    while (!failure && next < queries.length) {
      const index = next++;
      const query = queries[index];
      try {
        const payload = await execute({kind: "imagePage", categoryId: action.categoryId,
          page: 1, pageSize: action.pageSize, query});
        results[index] = {query, payload};
      } catch (error) {
        failure = failure || error;
      }
    }
  };
  await Promise.all(Array.from({length: Math.min(5, queries.length)}, worker));
  if (failure) throw failure;
  return results;
})()
