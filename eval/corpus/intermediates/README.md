# Intermediate certificates for the corpus download

Some publishers' HTTPS servers send their own certificate without the intermediate certificate that links it to a trusted root. Browsers fetch the missing intermediate from the address in the certificate (Authority Information Access); Python's `ssl` module does not, so `fetch.py` loads these files in addition to the system's trusted roots. Certificate verification stays on.

| File | Needed by | Issued by (root) | Source | SHA-256 fingerprint |
|---|---|---|---|---|
| `geotrust-tls-rsa-ca-g1.pem` | www.mevzuat.gov.tr, www.resmigazete.gov.tr | DigiCert Global Root G2 | http://cacerts.geotrust.com/GeoTrustTLSRSACAG1.crt | `C0:6E:30:7F:7C:FC:1D:32:FA:72:A4:C0:33:C8:7B:90:01:9A:F2:16:F0:77:5D:64:97:8A:2E:CA:6C:8A:23:0E` |
| `ssl2buy-emea-rsa-ov-ca.pem` | webdosya.csb.gov.tr | Sectigo Public Server Authentication Root R46 | http://crt.sectigo.com/SSL2BUYEMEARSAOrganizationValidationSecureServerCA.crt | `F7:AD:61:C4:F2:A7:4D:1B:E7:C0:58:0A:36:B2:C9:3D:FD:5E:8B:C1:58:86:07:1C:25:F4:E6:6D:C1:5B:BB:F8` |

Both were checked with `openssl verify` against the system roots on 2026-09-28. The GeoTrust intermediate expires in November 2027.
