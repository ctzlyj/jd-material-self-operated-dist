(async () => {
  const action = __JD_SELF_OPERATED_PRODUCT_ACTION__;
  const stateKey = "__jdMaterialProductScopeV1";
  const productApp = "3MC69M4R3HFKCQ4S01DN";
  const materialApp = "BD2QSA2XUESRKXAL1QKQ";
  const request = async (api, body, appId = productApp, vendorId = "") => {
    const headers = { "content-type": "application/json", "dsm-platform": "erp" };
    if (vendorId) {
      headers["belong-biz-id"] = vendorId;
      headers["belong-type"] = "200";
    }
    const response = await fetch(`https://sff.jd.com/api?${new URLSearchParams({v: "1.0", appId, api})}`, {
      method: "POST", credentials: "include", headers,
      signal: AbortSignal.timeout(30000), body: JSON.stringify(body),
    });
    const payload = await response.json();
    if (!response.ok || ![200, "200"].includes(payload.code)) {
      throw new Error(`product API failed HTTP ${response.status} code=${payload.code}`);
    }
    return payload.data;
  };
  const base = { source: "web", businessModel: "jxpop", newBusinessModel: 2, proxyBelongType: 200 };
  const user = await request("dsm.upload.user.UserAuthorityService.getUserInfo", { accessContext: base }, materialApp);
  const loginErp = String(user?.pin || "");
  if (!loginErp || (action.expectedErp && action.expectedErp !== loginErp)) {
    throw new Error("authenticated ERP does not match expected ERP; no product write is allowed");
  }
  if (!window[stateKey] || window[stateKey].loginErp !== loginErp) {
    const scopes = await request("dsm.upload.ware.WareApiService.getAllJxPopVenderShop", { accessContext: base }, materialApp);
    if (!Array.isArray(scopes) || scopes.length !== 1 || !scopes[0].venderId) {
      throw new Error("ambiguous or unavailable self-operated product scope");
    }
    window[stateKey] = { loginErp, vendorId: String(scopes[0].venderId) };
  }
  const state = window[stateKey];
  const accessContext = { source: "web", businessModel: "2", proxyBelongBizId: state.vendorId, originType: null };
  const call = (api, body) => request(api, { accessContext, ...body }, productApp, state.vendorId);
  if (action.kind === "inventoryPage") {
    const pageSize = Number(action.pageSize);
    if (!Number.isInteger(pageSize) || pageSize < 1) throw new Error("product page size must be a positive integer");
    const data = await call("dsm.product.manage.ProductInfoReadViewService.queryValidProductList", {
      productListQueryReq: {
        currentBizId: state.vendorId, productState: "11", filterErpCode: action.ownerErp || null,
        productIdList: action.spuIds || null, skuIdList: null, categoryIds: [], brandIdList: [],
        sortMap: { created: "asc" }, pageNum: Number(action.page), pageSize,
      },
    });
    return {
      total: Number(data.totalCount), page: Number(data.pageNo), loginErp,
      scope: action.ownerErp ? "explicit-owner-filter" : "available-permissions",
      rows: (data.data || []).map(item => ({
        spuId: String(item.productId), productName: String(item.productName || ""),
        declaredSkuCount: Number(item.productSkuInfoVO?.skuCount || 0),
        logo: String(item.logo || ""), score: item.healthScoreVO?.score ?? null,
      })),
    };
  }
  if (action.kind === "shortTitleRows") {
    const result = [];
    for (const spuId of action.spuIds || []) {
      const data = await call("dsm.product.manage.SkuInfoReadViewService.querySkuList", {
        skuListQueryReq: { productId: String(spuId), skuStatusList: [], sortMap: { created: "asc" } },
      });
      const rows = Array.isArray(data) ? data : (data?.totalCount === 0 && data.data === null ? [] : data?.data);
      if (!Array.isArray(rows)) throw new Error("short-title readback returned an unknown SKU schema");
      if (!Array.isArray(data) && Number(data.totalCount) !== rows.length) {
        throw new Error("short-title SKU page is incomplete; no write is allowed");
      }
      for (const sku of rows) {
        const featureMapKnown = Object.prototype.hasOwnProperty.call(sku, "skuFeatureMap") && (
          sku.skuFeatureMap === null || (typeof sku.skuFeatureMap === "object" && !Array.isArray(sku.skuFeatureMap))
        );
        result.push({
          productId: String(spuId), skuId: String(sku.skuId || ""),
          shortTitle: String(sku.skuFeatureMap?.shortTitle || ""),
          shortTitleKnown: featureMapKnown && (sku.skuFeatureMap?.shortTitle == null || typeof sku.skuFeatureMap.shortTitle === "string"),
        });
      }
    }
    return result;
  }
  throw new Error("unsupported product action");
})()
