(async () => {
  const action = __JD_SELF_OPERATED_UPLOAD_ACTION__;
  const endpoint = "https://sff.jd.com/api";
  const appId = "YYGSNPYN2EN5LVUEWU4Y";
  const cdnBase = "https://img10.360buyimg.com/imgzone/";
  const baseContext = { source: "web", businessModel: "self" };

  const request = async (api, body, accessContext) => {
    const query = new URLSearchParams({ v: "1.0", appId, api });
    const response = await fetch(`${endpoint}?${query}`, {
      method: "POST",
      signal: AbortSignal.timeout(30000),
      credentials: "include",
      headers: {
        "content-type": "application/json;charset=UTF-8",
        "dsm-platform": "erp",
      },
      body: JSON.stringify({ accessContext, ...(body || {}) }),
    });
    let payload;
    try {
      payload = await response.json();
    } catch (_error) {
      throw new Error(`image-space API returned non-JSON HTTP ${response.status}`);
    }
    if (!response.ok || ![200, "200"].includes(payload && payload.code)) {
      throw new Error(`image-space API failed HTTP ${response.status} code=${payload && payload.code}`);
    }
    return payload.data || {};
  };

  const call = async (api, body, terminal = false) => {
    const accessContext = { ...baseContext };
    if (terminal) accessContext.terminal = 0;
    return request(api, body, accessContext);
  };

  const normalize = (item) => {
    const path = String((item && (item.imgUrl || item.path)) || "").replace(/^\/+/, "");
    return {
      imageId: String((item && (item.imgId || item.id)) || ""),
      name: String((item && (item.imgName || item.name)) || ""),
      path,
      url: /^https?:\/\//i.test(path) ? path : (path ? `${cdnBase}${path}` : ""),
      categoryId: String((item && item.cateId) || action.categoryId || "0"),
    };
  };

  if (action.kind === "verifyIdentity") {
    const data = await call("dsm.media.image.zoneInfo.getUserZoneInfo", null);
    if (!action.expectedErp || String(data.userPin || "") !== action.expectedErp) {
      throw new Error("authenticated ERP does not match expected ERP in image space");
    }
    return { erpMatched: true };
  }

  if (action.kind === "imagePage") {
    const data = await call("dsm.media.image.imageApiService.queryImageAndCate", {
      imageQueryVo: {
        cateId: String(action.categoryId || "0"),
        qryKey: String(action.query || ""),
        page: Number(action.page),
        pageSize: Number(action.pageSize),
        onlyImage: true,
        orderByDate: "createDate_desc",
      },
    });
    return {
      page: Number(data.currPage ?? action.page),
      pageTotal: Number(data.pageTotal || 0),
      total: Number(data.imgDirTotal || 0),
      images: (data.imgList || []).map(normalize),
    };
  }

  if (action.kind === "uploadImage") {
    let fileData = String(action.fileData || "");
    if (action.fileInputId) {
      const files = Array.from(document.getElementById(action.fileInputId)?.files || []);
      const file = files.find(item => item.name === action.fileName);
      if (!file || file.name !== action.fileName) throw new Error("selected upload file does not match planned filename");
      if (files.filter(item => item.name === action.fileName).length !== 1) throw new Error("duplicate staged upload filename");
      if (action.expectedSha256) {
        const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
        const actual = Array.from(new Uint8Array(digest)).map(value => value.toString(16).padStart(2, "0")).join("");
        if (actual !== action.expectedSha256) throw new Error("staged image content hash does not match the approved file");
      }
      fileData = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onerror = () => reject(new Error("local image read failed"));
        reader.onload = () => resolve(String(reader.result).split(",")[1]);
        reader.readAsDataURL(file);
      });
    }
    if (action.shouldStop?.()) throw new Error("upload stopped before dispatch");
    const data = await call("dsm.media.image.imageApiService.uploadImage", {
      cateId: String(action.categoryId || "0"),
      fileData,
      fileName: String(action.fileName || ""),
    }, true);
    return normalize(data);
  }

  throw new Error("unsupported self-operated image-space action");
})()
