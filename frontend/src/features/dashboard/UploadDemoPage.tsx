/** Demo page for the file upload flow (task 2.9). */

import { FileUploadDemo } from './FileUploadDemo'

export function UploadDemoPage() {
  return (
    <section className="list-page" aria-label="文件上传演示">
      <h1>文件上传演示</h1>
      <p className="list-page-note">
        流程：申请授权 → 直传（含进度）→ 后端校验并登记。页面只持有短期直传地址，
        不持有 RustFS 长期密钥；登记响应丢失时可直接重试登记。
      </p>
      <FileUploadDemo />
    </section>
  )
}
