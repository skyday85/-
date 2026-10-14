fn main() {
    // Temporary development icon; replace with branded assets before release.
    let icon = "89504e470d0a1a0a0000000d4948445200000020000000200806000000737a7af4000000314944415478daedce410100400400302e851472e85fe8c4f0d9122cabe7c7a117c704040404040404040404040404040416120d01cd960913ae0000000049454e44ae426082";
    let path = std::path::Path::new("icons/icon.png");
    if !path.exists() {
        std::fs::create_dir_all("icons").expect("create icon directory");
        let bytes: Vec<u8> = icon.as_bytes().chunks_exact(2).map(|pair| {
            u8::from_str_radix(std::str::from_utf8(pair).expect("icon hex"), 16).expect("icon byte")
        }).collect();
        std::fs::write(path, bytes).expect("write temporary icon");
    }
    tauri_build::build()
}
