(async () => {
  const action = __JD_SELF_OPERATED_ACTION__;
  const stateKey = "__jdMaterialSelfOperatedReadonlyV1";
  const endpoint = "https://sff.jd.com/api";
  const appId = "BD2QSA2XUESRKXAL1QKQ";
  const baseContext = {
    source: "web", businessModel: "jxpop", buId: null,
    newBusinessModel: 2, proxyBelongType: 200,
  };
  const mask = (value) => {
    const text = String(value || "");
    return text ? `***${text.slice(-4)}` : "";
  };

  const request = async (api, body, accessContext) => {
    const query = new URLSearchParams({ v: "1.0", appId, api });
    const url = `${endpoint}?${query}`;
    const headers = {
      "content-type": "application/json;charset=UTF-8",
      "dsm-platform": "erp",
    };
    const requestBody = { accessContext, ...(body || {}) };
    let payload;
    let status;
    let ok;
    if (window.oswAxios && typeof window.oswAxios.post === "function") {
      let response;
      try {
        response = await window.oswAxios.post(url, requestBody, {
          withCredentials: true,
          timeout: 30000,
          headers,
        });
      } catch (error) {
        response = error && error.response;
        if (!response) throw error;
      }
      status = Number(response.status || 0);
      ok = status >= 200 && status < 300;
      payload = response.data;
    } else {
      if (typeof window.fetch !== "function") {
        throw new Error("official page request runtime is unavailable");
      }
      const response = await window.fetch(url, {
        method: "POST",
        signal: AbortSignal.timeout(30000),
        credentials: "include",
        headers,
        body: JSON.stringify(requestBody),
      });
      status = response.status;
      ok = response.ok;
      try {
        payload = await response.json();
      } catch (_error) {
        throw new Error(`material API returned non-JSON HTTP ${status}`);
      }
    }
    if (!ok || ![200, "200"].includes(payload && payload.code)) {
      const message = payload && (payload.msg || payload.message || (payload.data && payload.data.msg));
      throw new Error(
        `material API failed HTTP ${status} code=${payload && payload.code}` +
        (message ? ` message=${message}` : ""),
      );
    }
    return payload.data || {};
  };

  const call = async (api, body) => {
    const state = window[stateKey];
    if (!state || !state.vendorId) throw new Error("self-operated shop is not initialized");
    return request(api, body, {
      ...baseContext,
      proxyVendorCode: state.vendorId,
      belongType: 200,
      proxyBelongBizId: state.vendorId,
    });
  };

  const materialSlots = [
    ["smartPicWhite", 31, 1], ["smartThroughPic", 36, 1],
    ["smartPicScene", 32, 1], ["smartPicScene2", 32, 2], ["smartPicSell", 33, 1],
  ];

  const normalizeCurrentChild = (item, spuId) => {
    const featureMap = item.skuFeatureMap || {};
    const directKnown = Object.prototype.hasOwnProperty.call(item, "shortTitle");
    const mappedKnown = Object.prototype.hasOwnProperty.call(featureMap, "shortTitle");
    const explicitSupport = new Map((item.supportMaterialInfo || []).map((value) => [
      Number(value.materialType), Number(value.isSupport),
    ]));
    const supportedTypes = [];
    const materials = [];
    for (const [field, type, order] of materialSlots) {
      if (!Object.prototype.hasOwnProperty.call(item, field) || explicitSupport.get(type) === 0) continue;
      if (!supportedTypes.includes(type)) supportedTypes.push(type);
      const value = item[field];
      const url = value && (value.smartPicList || []).find(Boolean);
      if (value) materials.push({ type, order, status: Number(value.status || 0), url: String(url || ""),
        ...(value.desc ? {reason: String(value.desc)} : {}),
      });
    }
    const directPoints = (item.smartContentSellList || []).filter(Boolean);
    const nestedPoints = ((item.smartSellPoint || {}).smartPicList || []).filter(Boolean);
    const sellPoints = (directPoints.length ? directPoints : nestedPoints).map((value) => String(value));
    const skuId = String(item.skuId || item.productId || "");
    return {
      sku: {
        skuId,
        spuId: String(item.parentSpuId || spuId || ""),
        skuName: String(item.skuName || item.productName || ""),
        logo: String(item.logo || item.imageUrl || ""),
        supportedTypes,
        materials,
        shortTitleKnown: directKnown || mappedKnown,
        shortTitle: directKnown ? String(item.shortTitle || "") : String(featureMap.shortTitle || ""),
      },
      text: {
        skuId,
        sellPoints,
        sellMaxNum: Number(item.sellMaxNum || 3),
        shortTitleKnown: directKnown || mappedKnown,
        shortTitle: directKnown ? String(item.shortTitle || "") : String(featureMap.shortTitle || ""),
      },
    };
  };

  const currentPage = (data) => {
    if (data && Array.isArray(data.data)) return data;
    return (data || {}).pageData || {};
  };

  const currentQuery = (productIds, pageIndex, pageSize) => ({
    productQuery: {
      productIds, skuIds: [], queryAllSKu: true, salesNumSort: 2,
      pageIndex, pageSize, sceneType: 1,
    },
  });

  if (action.kind === "initialize") {
    const user = await request("dsm.upload.user.UserAuthorityService.getUserInfo", {}, baseContext);
    const loginErp = String(user.pin || "");
    if (!loginErp || (action.expectedErp && action.expectedErp !== loginErp)) {
      throw new Error("authenticated ERP does not match expected ERP");
    }
    const data = await request("dsm.upload.ware.WareApiService.getAllJxPopVenderShop", {}, baseContext);
    const shops = (Array.isArray(data) ? data : []).map((item) => ({
      vendorId: String(item.venderId || ""),
      shopName: String(item.venderName || "").trim(),
    })).filter((item) => item.vendorId && item.shopName);
    const expected = String(action.expectedShopName || "").trim();
    const matches = expected ? shops.filter((item) => item.shopName === expected) : shops;
    if (!shops.length) throw new Error("shop list is empty");
    if (!matches.length) throw new Error("expected shop name does not match");
    if (matches.length !== 1) throw new Error("multiple shops require --expected-shop-name");
    window[stateKey] = { vendorId: matches[0].vendorId, shopName: matches[0].shopName, loginErp };
    return {
      loginErp,
      shopName: matches[0].shopName,
      maskedShopId: mask(matches[0].vendorId),
      candidateShops: shops.map((item) => ({ shopName: item.shopName, maskedShopId: mask(item.vendorId) })),
    };
  }

  if (action.kind === "spuPage") {
    const page = Number(action.page);
    const pageSize = Number(action.pageSize);
    const data = await call(
      "dsm.upload.material.ware.queryProductMaterialListNew",
      currentQuery((action.spuIds || []).map(String), page, pageSize),
    );
    const pageData = currentPage(data);
    const rows = (pageData.data || []).filter(Boolean).map((item) => {
      const first = (item.childList || []).find(Boolean) || {};
      return {
        spuId: String(item.productId || ""),
        productName: String(item.productName || first.productName || ""),
        declaredSkuCount: Number(item.childCount ?? (item.childList || []).length),
        score: item.score == null ? (first.score == null ? null : first.score) : item.score,
        logo: String(item.logo || item.imageUrl || first.imageUrl || ""),
      };
    });
    return { total: Number(pageData.count ?? pageData.total ?? rows.length), page, rows };
  }

  if (action.kind === "inspectSpuDetails") {
    const ids = (action.spuIds || []).map(String);
    if (!ids.length || ids.length > 5 || new Set(ids).size !== ids.length || ids.some(id => !/^\d+$/.test(id))) {
      throw new Error("material detail reads require one to five distinct SPUs");
    }
    return Promise.all(ids.map(async (spuId) => {
      try {
        const data = await call("dsm.upload.material.ware.getProductAllSkuMaterialInfo", {
          apiProductQuery: { productId: spuId, sceneType: 1, skuFieldSet: ["saleAttrs", "logo", "sellMaxNum"] },
        });
        if (!Array.isArray(data.childList)) throw new Error("material detail has no complete child list");
        if (data.childCount != null && Number(data.childCount) !== data.childList.length) {
          throw new Error("material detail child count mismatch");
        }
        const children = data.childList.map((item) => normalizeCurrentChild(item, spuId));
        return { spuId, skus: children.map(item => item.sku), textChildren: children.map(item => item.text), errors: [] };
      } catch (error) {
        return { spuId, skus: [], textChildren: [], errors: [String(error.message || error)] };
      }
    }));
  }

  if (action.kind === "inspectSpus") {
    const ids = (action.spuIds || []).map(String);
    const data = await call(
      "dsm.upload.material.ware.queryProductMaterialListNew",
      currentQuery(ids, 1, Math.max(1, Math.min(50, ids.length))),
    );
    const parents = currentPage(data).data || [];
    const bySpu = new Map(parents.filter(Boolean).map((item) => [String(item.productId || ""), item]));
    return ids.map((spuId) => {
      const parent = bySpu.get(spuId);
      if (!parent) return { spuId, skus: [], textChildren: [], errors: ["product detail lookup omitted SPU"] };
      const children = (parent.childList || []).filter(Boolean).map((item) => normalizeCurrentChild(item, spuId));
      return {
        spuId,
        skus: children.map((item) => item.sku),
        textChildren: children.map((item) => item.text),
        errors: [],
      };
    });
  }

  throw new Error("unsupported read-only action");
})()
