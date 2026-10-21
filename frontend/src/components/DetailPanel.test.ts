import { describe, expect, it } from "vitest";

import { artifactUrl, tdocZipUrl } from "./DetailPanel";

describe("artifactUrl", () => {
  it("uses the browser host for 3GPP FTP links", () => {
    expect(
      artifactUrl(
        "ftp://ftp.3gpp.org/Meetings_3GPP_SYNC/SA3",
        "Inbox/Drafts/draft S3-264403-r1_LS reply SA5.docx",
      ),
    ).toBe(
      "https://www.3gpp.org/ftp/Meetings_3GPP_SYNC/SA3/Inbox/Drafts/draft%20S3-264403-r1_LS%20reply%20SA5.docx",
    );
  });

  it("keeps other hosts unchanged", () => {
    expect(
      artifactUrl("ftp://10.10.10.10/Meetings_3GPP_SYNC/SA3", "Inbox/a.docx"),
    ).toBe("https://10.10.10.10/ftp/Meetings_3GPP_SYNC/SA3/Inbox/a.docx");
    expect(artifactUrl(null, "Inbox/a.docx")).toBeNull();
  });
});

describe("tdocZipUrl", () => {
  it("links the fixed Docs ZIP filename for a TDoc", () => {
    expect(
      tdocZipUrl(
        "ftp://ftp.3gpp.org/Meetings_3GPP_SYNC/SA3",
        "s3-264202",
      ),
    ).toBe(
      "https://www.3gpp.org/ftp/Meetings_3GPP_SYNC/SA3/Docs/S3-264202.zip",
    );
  });

  it("returns null without an endpoint", () => {
    expect(tdocZipUrl(null, "S3-264202")).toBeNull();
  });
});
