{
  description = "Mirko - local-first 3GPP SA3 contribution tracker";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = f:
        nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in {
      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = with pkgs; [
            python314
            python314Packages.pytest
            python314Packages.fastapi
            python314Packages.uvicorn
            python314Packages.pydantic
            python314Packages.openpyxl
            python314Packages.hypothesis
            lftp
          ];
        };
      });
    };
}
