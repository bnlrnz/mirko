import { describe, expect, it } from "vitest";

import { artifactUrl } from "./DetailPanel";

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
