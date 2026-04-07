// Fixture for testing CALLS edge extraction in TypeScript

function helper(): string {
    return "ok";
}

function main(): void {
    // Calls helper() — should produce a CALLS edge main→helper
    const result = helper();
}

class Service {
    process(data: string): string {
        // Calls this.validate() and this.transform()
        if (this.validate(data)) {
            return this.transform(data);
        }
        return "";
    }

    validate(data: string): boolean {
        return data.length > 0;
    }

    transform(data: string): string {
        return data.toUpperCase();
    }
}
