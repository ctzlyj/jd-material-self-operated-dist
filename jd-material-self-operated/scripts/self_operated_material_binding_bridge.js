(async () => {
  const action = __JD_SELF_OPERATED_BINDING_ACTION__;
  const stateKey = "__jdMaterialSelfOperatedReadonlyV1";
  const endpoint = "https://sff.jd.com/api";
  const appId = "BD2QSA2XUESRKXAL1QKQ";
  const baseContext = { source: "web", businessModel: "jxpop", newBusinessModel: 2, proxyBelongType: 200 };

  const request = async (api, body) => {
    const state = window[stateKey];
    if (!state || !state.vendorId) throw new Error("self-operated shop is not initialized");
    const query = new URLSearchParams({ v: "1.0", appId, api });
    const response = await fetch(`${endpoint}?${query}`, {
      method: "POST",
      signal: AbortSignal.timeout(30000),
      credentials: "include",
      headers: {
        "content-type": "application/json;charset=UTF-8",
        "dsm-platform": "erp",
      },
      body: JSON.stringify({
        accessContext: { ...baseContext, proxyVendorCode: state.vendorId, proxyBelongBizId: state.vendorId, belongType: 200 },
        ...(body || {}),
      }),
    });
    let payload;
    try {
      payload = await response.json();
    } catch (_error) {
      throw new Error(`material binding API returned non-JSON HTTP ${response.status}`);
    }
    if (!response.ok || ![200, "200"].includes(payload && payload.code)) {
      throw new Error(`material binding API failed HTTP ${response.status} code=${payload && payload.code}`);
    }
    return payload.data;
  };

  const expectedErp = action.expectedErp || window[stateKey]?.loginErp;
  if (expectedErp) {
    const user = await request("dsm.upload.user.UserAuthorityService.getUserInfo", {});
    if (String(user?.pin || "") !== expectedErp) throw new Error("authenticated ERP changed; binding stopped");
  }

  if (action.kind === "bindImages") {
    if (action.shouldStop?.()) throw new Error("binding stopped before dispatch");
    const data = await request("dsm.media.material.imageRelations.batchBind", action.body);
    const errors = Array.isArray(data)
      ? data.filter((item) => item && item.errorMsg).map((item) => String(item.errorMsg))
      : [];
    return { ok: errors.length === 0, errors, ...(errors.length ? { error: errors.join("；") } : {}) };
  }

  if (action.kind === "saveSellingPoints") {
    if (action.shouldStop?.()) throw new Error("binding stopped before dispatch");
    const data = await request("dsm.media.text.shortTitleSeller.save", action.body);
    return { ok: data === "success" || data === true || data == null, errors: [], raw: data };
  }

  throw new Error("unsupported self-operated material binding action");
})()
